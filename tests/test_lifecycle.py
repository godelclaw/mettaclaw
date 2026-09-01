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

    def test_running_latch_without_watcher_remains_enabled(self):
        lifecycle._write(lifecycle.RUNNING)
        with mock.patch.object(lifecycle, "watcher_lease_healthy",
                               return_value=False):
            self.assertEqual(lifecycle.cognition_enabled(), 1)
            self.assertEqual(
                lifecycle.view(), "running (operator latch)"
            )

    def test_start_sets_latch_without_touching_watcher(self):
        with mock.patch.object(
                lifecycle, "_systemctl",
                side_effect=AssertionError("start touched watcher")):
            reply = lifecycle.start()
        self.assertIn("cognition enabled", reply)
        self.assertEqual(lifecycle.durable_state(), lifecycle.RUNNING)

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

    def test_expired_watcher_receipt_does_not_revoke_cognition(self):
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
            self.assertEqual(lifecycle.cognition_enabled(), 1)

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

    def test_stop_sets_latch_without_touching_watcher(self):
        lifecycle._write(lifecycle.RUNNING)
        with mock.patch.object(
                lifecycle, "_systemctl",
                side_effect=AssertionError("stop touched watcher")):
            reply = lifecycle.stop()
        self.assertIn("cognition revoked", reply)
        self.assertEqual(lifecycle.durable_state(), lifecycle.STOPPED)


if __name__ == "__main__":
    unittest.main(verbosity=2)
