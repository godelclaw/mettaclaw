import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import runtime_health  # noqa: E402


class RuntimeHealthTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = pathlib.Path(self.temporary.name)
        self.channel = root / "channel.json"
        self.working = root / "working.json"
        self.cognitive = root / "cognitive.json"
        self.mode = root / "mode.json"
        self.environment = mock.patch.dict(os.environ, {
            "METTACLAW_TELEGRAM_HEALTH_PATH": str(self.channel),
            "METTACLAW_WORKING_SET_PATH": str(self.working),
            "METTACLAW_COGNITIVE_HEALTH_PATH": str(self.cognitive),
            "METTACLAW_LOOP_MODE_PATH": str(self.mode),
            "METTACLAW_COGNITIVE_STALE_SECONDS": "300",
            "METTACLAW_DEPLOYED_COMMIT": "abcdef0123456789",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def write(self, path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_healthy_wait_is_not_mistaken_for_a_hang(self):
        self.write(self.channel, {
            "menu_status": "ok", "last_poll_ok_at": 999,
            "loop_status": "waiting", "waiting_until": 1200,
        })
        self.write(self.working, {"saved_at": 1})
        with mock.patch.object(runtime_health.memory_health, "drift",
                               return_value=(100, 95, 5)), \
             mock.patch.object(runtime_health.memory_health, "threshold",
                               return_value=20), \
             mock.patch.object(runtime_health, "_generation",
                               return_value="abcdef012345"):
            value = runtime_health.status(now=1000)
        self.assertEqual(value["state"], "ok")
        self.assertEqual(value["generation"], "abcdef012345")

    def test_stale_poll_and_awake_loop_fail_independently(self):
        self.write(self.channel, {
            "menu_status": "ok", "last_poll_ok_at": 100,
            "loop_status": "awake", "waiting_until": 0,
        })
        self.write(self.working, {"saved_at": 1})
        with mock.patch.object(runtime_health.memory_health, "drift",
                               return_value=(100, 100, 0)), \
             mock.patch.object(runtime_health.memory_health, "threshold",
                               return_value=20):
            value = runtime_health.status(now=1000)
        self.assertIn("telegram-poll-stale", value["problems"])
        self.assertIn("cognitive-boundary-stale", value["problems"])

    def test_fresh_completed_model_turn_is_healthy_when_armed(self):
        self.write(self.channel, {
            "menu_status": "ok", "last_poll_ok_at": 999,
            "loop_status": "waiting", "waiting_until": 1200,
        })
        self.write(self.working, {"saved_at": 999, "loops": 5})
        self.write(self.cognitive, {
            "last_completed_at": 995, "completed_count": 4,
            "pending_since": 0, "last_outcome": "completed",
        })
        with mock.patch.object(runtime_health.memory_health, "drift",
                               return_value=(100, 100, 0)), \
             mock.patch.object(runtime_health.memory_health, "threshold",
                               return_value=20):
            value = runtime_health.status(now=1000)
        self.assertNotIn("model-turn-stale", value["problems"])
        self.assertEqual(value["model_turn_age_seconds"], 5)

    def test_old_pending_turn_detects_empty_spinning(self):
        self.write(self.channel, {
            "menu_status": "ok", "last_poll_ok_at": 999,
            "loop_status": "waiting", "waiting_until": 1200,
        })
        self.write(self.working, {"saved_at": 999, "loops": 42})
        self.write(self.cognitive, {
            "pending_since": 600, "last_expected_at": 999,
            "expected_count": 300, "completed_count": 0,
        })
        with mock.patch.object(runtime_health.memory_health, "drift",
                               return_value=(100, 100, 0)), \
             mock.patch.object(runtime_health.memory_health, "threshold",
                               return_value=20):
            value = runtime_health.status(now=1000)
        self.assertIn("model-turn-overdue", value["problems"])
        self.assertEqual(value["model_turn_pending_age_seconds"], 400)

    def test_new_pending_turn_gets_grace_despite_old_completion(self):
        self.write(self.channel, {
            "menu_status": "ok", "last_poll_ok_at": 999,
            "loop_status": "awake", "waiting_until": 0,
        })
        self.write(self.working, {"saved_at": 999, "loops": 5})
        self.write(self.cognitive, {
            "pending_since": 995, "last_completed_at": 100,
            "expected_count": 2, "completed_count": 1,
        })
        with mock.patch.object(runtime_health.memory_health, "drift",
                               return_value=(100, 100, 0)), \
             mock.patch.object(runtime_health.memory_health, "threshold",
                               return_value=20):
            value = runtime_health.status(now=1000)
        self.assertNotIn("model-turn-stale", value["problems"])
        self.assertNotIn("model-turn-overdue", value["problems"])

    def test_intentional_default_idle_needs_no_model_receipt(self):
        self.write(self.channel, {
            "menu_status": "ok", "last_poll_ok_at": 999,
            "loop_status": "waiting", "waiting_until": 1200,
            "started_at": 1,
        })
        self.write(self.working, {"saved_at": 999, "loops": 0})
        self.write(self.mode, {"mode": "default", "autonomy_paused": False})
        with mock.patch.object(runtime_health.memory_health, "drift",
                               return_value=(100, 100, 0)), \
             mock.patch.object(runtime_health.memory_health, "threshold",
                               return_value=20):
            value = runtime_health.status(now=1000)
        self.assertFalse(value["cognition_required"])
        self.assertNotIn("model-turn-receipt-missing", value["problems"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
