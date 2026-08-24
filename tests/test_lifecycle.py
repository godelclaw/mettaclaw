import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import lifecycle  # noqa: E402


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = pathlib.Path(self.temporary.name) / "lifecycle.json"
        self.deployment = pathlib.Path(self.temporary.name) / "deployment.json"
        self.environment = mock.patch.dict(os.environ, {
            "METTACLAW_LIFECYCLE_PATH": str(self.path),
            "METTACLAW_DEPLOYMENT_WATCH_SERVICE": "watch.service",
            "METTACLAW_DEPLOYMENT_WATCH_TIMER": "watch.timer",
            "METTACLAW_DEPLOYMENT_STATE_PATH": str(self.deployment),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_missing_and_corrupt_state_fail_closed(self):
        with mock.patch.object(lifecycle, "watcher_active", return_value=True):
            self.assertEqual(lifecycle.cognition_enabled(), 0)
            self.path.write_text("not-json", encoding="utf-8")
            self.assertEqual(lifecycle.cognition_enabled(), 0)
            self.path.write_text(
                json.dumps({"schema": 1, "state": "surprise"}),
                encoding="utf-8",
            )
            self.assertEqual(lifecycle.cognition_enabled(), 0)

    def test_running_latch_without_watcher_fails_closed(self):
        lifecycle._write(lifecycle.RUNNING)
        with mock.patch.object(lifecycle, "watcher_active", return_value=False):
            self.assertEqual(lifecycle.cognition_enabled(), 0)
            self.assertIn("fail-closed", lifecycle.view())

    def test_start_grants_only_after_watcher_is_active(self):
        calls = []

        def systemctl(*args):
            calls.append(args)
            return (0, "")

        with mock.patch.object(lifecycle, "_systemctl", side_effect=systemctl), \
             mock.patch.object(lifecycle, "watcher_active", return_value=True), \
             mock.patch.object(lifecycle, "_fresh_probe_healthy",
                               return_value=(True, "healthy")):
            reply = lifecycle.start()
        self.assertIn("cognition enabled", reply)
        self.assertEqual(lifecycle.durable_state(), lifecycle.RUNNING)
        self.assertEqual(calls[0],
                         ("unmask", "watch.service", "watch.timer"))
        self.assertEqual(calls[1], ("enable", "--now", "watch.timer"))
        self.assertEqual(calls[2], ("start", "watch.service"))

    def test_watcher_probe_runs_while_latch_is_still_stopped(self):
        states = []

        def systemctl(*_args):
            states.append(lifecycle.durable_state())
            return (0, "")

        with mock.patch.object(lifecycle, "_systemctl", side_effect=systemctl), \
             mock.patch.object(lifecycle, "watcher_active", return_value=True), \
             mock.patch.object(lifecycle, "_fresh_probe_healthy",
                               return_value=(True, "healthy")):
            lifecycle.start()
        self.assertTrue(states)
        self.assertEqual(set(states), {lifecycle.STOPPED})

    def test_failed_watcher_probe_remains_stopped_and_disables_timer(self):
        calls = []

        def systemctl(*args):
            calls.append(args)
            if args == ("start", "watch.service"):
                return (1, "probe failed")
            return (0, "")

        with mock.patch.object(lifecycle, "_systemctl", side_effect=systemctl), \
             mock.patch.object(lifecycle, "watcher_active", return_value=True), \
             mock.patch.object(lifecycle, "_fresh_probe_healthy",
                               return_value=(False, "probe failed")):
            reply = lifecycle.start()
        self.assertIn("probe was not healthy", reply)
        self.assertEqual(lifecycle.durable_state(), lifecycle.STOPPED)
        self.assertIn(("disable", "--now", "watch.timer"), calls)

    def test_probe_requires_fresh_matching_problem_free_observation(self):
        now = 1000.0
        base = {
            "candidate": "abc",
            "last_observation": {
                "observed_at": now,
                "head": "abc",
                "active": True,
                "problems": [],
            },
        }
        self.deployment.write_text(json.dumps(base), encoding="utf-8")
        self.assertEqual(lifecycle._fresh_probe_healthy(now),
                         (True, "healthy"))
        base["last_observation"]["problems"] = ["telegram-poll-stale"]
        self.deployment.write_text(json.dumps(base), encoding="utf-8")
        healthy, detail = lifecycle._fresh_probe_healthy(now)
        self.assertFalse(healthy)
        self.assertIn("telegram-poll-stale", detail)
        base["last_observation"]["problems"] = []
        base["last_observation"]["observed_at"] = now - 1
        self.deployment.write_text(json.dumps(base), encoding="utf-8")
        self.assertFalse(lifecycle._fresh_probe_healthy(now)[0])

    def test_failed_start_leaves_stopped_latch(self):
        lifecycle._write(lifecycle.RUNNING)
        with mock.patch.object(lifecycle, "_systemctl",
                               return_value=(1, "failed")), \
             mock.patch.object(lifecycle, "watcher_active",
                               return_value=False):
            reply = lifecycle.start()
        self.assertIn("remains stopped", reply)
        self.assertEqual(lifecycle.durable_state(), lifecycle.STOPPED)

    def test_stop_revokes_before_touching_watcher(self):
        lifecycle._write(lifecycle.RUNNING)
        states_at_calls = []

        def systemctl(*_args):
            states_at_calls.append(lifecycle.durable_state())
            return (0, "inactive")

        with mock.patch.object(lifecycle, "_systemctl", side_effect=systemctl), \
             mock.patch.object(lifecycle, "watcher_active", return_value=False):
            reply = lifecycle.stop()
        self.assertIn("cognition revoked", reply)
        self.assertTrue(states_at_calls)
        self.assertEqual(set(states_at_calls), {lifecycle.STOPPED})


if __name__ == "__main__":
    unittest.main(verbosity=2)
