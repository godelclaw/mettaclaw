import json
import os
import pathlib
import sys
import tempfile
import threading
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
        with mock.patch.object(lifecycle, "watcher_lease_healthy",
                               return_value=True):
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
        with mock.patch.object(lifecycle, "watcher_lease_healthy",
                               return_value=False):
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

    def test_hot_path_uses_bounded_receipt_without_systemctl(self):
        now = 1000.0
        self.deployment.write_text(json.dumps({
            "candidate": "abc",
            "last_observation": {
                "observed_at": now - 10,
                "head": "abc",
                "active": True,
                "problems": [],
            },
        }), encoding="utf-8")
        lifecycle._write(lifecycle.RUNNING)
        with mock.patch.dict(os.environ, {
                "METTACLAW_WATCHER_LEASE_SECONDS": "90"}), \
             mock.patch.object(lifecycle, "_systemctl",
                               side_effect=AssertionError("hot path blocked")):
            self.assertTrue(lifecycle.watcher_lease_healthy(now))
            with mock.patch.object(lifecycle.time, "time", return_value=now):
                self.assertEqual(lifecycle.cognition_enabled(), 1)
                self.assertIn("running", lifecycle.view())

    def test_expired_watcher_receipt_revokes_cognition(self):
        now = 1000.0
        self.deployment.write_text(json.dumps({
            "candidate": "abc",
            "last_observation": {
                "observed_at": now - 91,
                "head": "abc",
                "active": True,
                "problems": [],
            },
        }), encoding="utf-8")
        lifecycle._write(lifecycle.RUNNING)
        with mock.patch.dict(os.environ, {
                "METTACLAW_WATCHER_LEASE_SECONDS": "90"}), \
             mock.patch.object(lifecycle.time, "time", return_value=now):
            self.assertEqual(lifecycle.cognition_enabled(), 0)

    def test_service_pins_shared_authority_paths_after_legacy_environment(self):
        unit = (ROOT / "systemd" / "pettaclaw-godel.service").read_text(
            encoding="utf-8"
        )
        legacy = unit.index("EnvironmentFile=-%h/.config/pettaclaw/godel-runtime.env")
        lifecycle_path = unit.index("Environment=METTACLAW_LIFECYCLE_PATH=")
        deployment_path = unit.index(
            "Environment=METTACLAW_DEPLOYMENT_STATE_PATH="
        )
        self.assertLess(legacy, lifecycle_path)
        self.assertLess(legacy, deployment_path)

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

    def test_stop_preempts_slow_start_and_stale_start_cannot_grant(self):
        start_blocked = threading.Event()
        release_start = threading.Event()
        stop_cleanup_started = threading.Event()

        def systemctl(*args):
            if args == ("unmask", "watch.service", "watch.timer"):
                start_blocked.set()
                release_start.wait(2)
            elif args == ("disable", "--now", "watch.timer"):
                stop_cleanup_started.set()
            return (0, "active")

        replies = []
        with mock.patch.object(lifecycle, "_systemctl",
                               side_effect=systemctl), \
             mock.patch.object(lifecycle, "watcher_active",
                               return_value=False), \
             mock.patch.object(lifecycle, "_fresh_probe_healthy",
                               return_value=(True, "healthy")):
            starter = threading.Thread(
                target=lambda: replies.append(lifecycle.start())
            )
            starter.start()
            self.assertTrue(start_blocked.wait(1))

            # Revocation is durable before stop performs any slow cleanup.
            stopper = threading.Thread(target=lifecycle.stop)
            stopper.start()
            self.assertTrue(stop_cleanup_started.wait(1))
            self.assertEqual(lifecycle.durable_state(), lifecycle.STOPPED)

            release_start.set()
            starter.join(2)
            stopper.join(2)

        self.assertFalse(starter.is_alive())
        self.assertFalse(stopper.is_alive())
        self.assertIn("start cancelled", replies[0])
        self.assertEqual(lifecycle.durable_state(), lifecycle.STOPPED)


if __name__ == "__main__":
    unittest.main(verbosity=2)
