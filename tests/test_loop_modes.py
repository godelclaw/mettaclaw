import json
import os
import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import loop_modes  # noqa: E402


class LoopModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous = os.environ.get("METTACLAW_LOOP_MODE_PATH")
        self.path = pathlib.Path(self.tmp.name) / "loop_mode.json"
        os.environ["METTACLAW_LOOP_MODE_PATH"] = str(self.path)

    def tearDown(self):
        if self.previous is None:
            os.environ.pop("METTACLAW_LOOP_MODE_PATH", None)
        else:
            os.environ["METTACLAW_LOOP_MODE_PATH"] = self.previous
        self.tmp.cleanup()

    def test_default_is_agent_policy(self):
        self.assertEqual(loop_modes.current_mode(), "agent")

    def test_historical_names_are_compatibility_aliases(self):
        for historical, current in (("default", "agent"),
                                    ("generic", "agent"),
                                    ("claw23", "iter")):
            self.path.write_text(json.dumps({"mode": historical}) + "\n")
            self.assertEqual(loop_modes.current_mode(), current)
            self.assertIn("alias", loop_modes.set_mode(historical))
            self.assertEqual(json.loads(self.path.read_text())["mode"], current)
            self.assertNotIn(historical, loop_modes.MODES)

    def test_iter_persists(self):
        self.assertIn("persists", loop_modes.set_mode("iter"))
        self.assertEqual(loop_modes.current_mode(), "iter")
        self.assertEqual(json.loads(self.path.read_text())["mode"], "iter")

    def test_explicit_rest_state_is_persistent_and_reversible(self):
        loop_modes.set_mode("iter")
        self.assertEqual(loop_modes.pause_autonomy(), 1)
        self.assertEqual(loop_modes.autonomy_paused(), 1)
        self.assertEqual(loop_modes.resume_autonomy(), 1)
        self.assertEqual(loop_modes.autonomy_paused(), 0)

    def test_coding_is_selectable(self):
        loop_modes.set_mode("coding")
        self.assertEqual(loop_modes.current_mode(), "coding")

    def test_wait_result_normalization_only_reports_adapter_fact(self):
        self.assertEqual(loop_modes.wait_timed_out("rested 60s"), 1)
        self.assertEqual(loop_modes.wait_timed_out("woken by operator message"), 0)

    def test_unknown_mode_does_not_change_state(self):
        loop_modes.set_mode("iter")
        self.assertIn("failed", loop_modes.set_mode("unknown"))
        self.assertEqual(loop_modes.current_mode(), "iter")


if __name__ == "__main__":
    unittest.main()
