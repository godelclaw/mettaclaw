import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import cognitive_health  # noqa: E402


class CognitiveHealthTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = pathlib.Path(self.temporary.name) / "cognitive.json"
        self.environment = mock.patch.dict(os.environ, {
            "METTACLAW_COGNITIVE_HEALTH_PATH": str(self.path),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def state(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def test_repeated_expectations_preserve_original_pending_time(self):
        cognitive_health.expect_turn("claw23", now=100)
        cognitive_health.expect_turn("claw23", now=200)
        value = self.state()
        self.assertEqual(value["pending_since"], 100)
        self.assertEqual(value["last_expected_at"], 200)
        self.assertEqual(value["expected_count"], 2)

    def test_completion_discharges_obligation_without_content(self):
        cognitive_health.expect_turn("generic", now=100)
        cognitive_health.turn_started("synthetic", now=101)
        cognitive_health.turn_completed(37, now=102)
        value = self.state()
        self.assertEqual(value["pending_since"], 0)
        self.assertEqual(value["last_completed_at"], 102)
        self.assertEqual(value["last_response_bytes"], 37)
        self.assertNotIn("prompt", value)
        self.assertNotIn("response", value)

    def test_failure_leaves_obligation_pending(self):
        cognitive_health.expect_turn("generic", now=100)
        cognitive_health.turn_failed("ReadTimeout", now=150)
        value = self.state()
        self.assertEqual(value["pending_since"], 100)
        self.assertEqual(value["last_failure_type"], "readtimeout")
        self.assertEqual(value["last_outcome"], "failed")

    def test_receipt_failure_never_interrupts_cognition(self):
        with mock.patch.object(cognitive_health, "_write",
                               side_effect=OSError("read-only")):
            self.assertEqual(cognitive_health.expect_turn(now=100), 0)
            self.assertEqual(cognitive_health.turn_started(now=101), 0)
            self.assertEqual(cognitive_health.turn_completed(now=102), 0)
            self.assertEqual(cognitive_health.turn_failed(now=103), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
