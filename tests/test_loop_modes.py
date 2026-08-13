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

    def test_default_is_generic(self):
        self.assertEqual(loop_modes.current_mode(), "generic")
        self.assertEqual(loop_modes.wait_seconds(0, 1), 1)
        self.assertEqual(loop_modes.autonomous_ready(0, "rested 1s"), 0)

    def test_claw23_persists_and_renews_after_sixty_second_wait(self):
        self.assertIn("persists", loop_modes.set_mode("claw23"))
        self.assertEqual(loop_modes.current_mode(), "claw23")
        self.assertEqual(loop_modes.wait_seconds(1, 1), 1)
        self.assertEqual(loop_modes.wait_seconds(0, 1), 60)
        self.assertEqual(loop_modes.autonomous_ready(0, "rested 60s"), 1)
        self.assertEqual(loop_modes.autonomous_ready(0, "woken by operator message"), 0)
        self.assertEqual(json.loads(self.path.read_text())["mode"], "claw23")

    def test_explicit_longer_rest_is_preserved_and_blocks_renewal(self):
        loop_modes.set_mode("claw23")
        self.assertEqual(loop_modes.pause_autonomy(), 1)
        self.assertEqual(loop_modes.wait_seconds(0, 600), 600)
        self.assertEqual(loop_modes.autonomous_ready(0, "rested 600s"), 0)
        self.assertEqual(loop_modes.resume_autonomy(), 1)
        self.assertEqual(loop_modes.autonomous_ready(0, "rested 60s"), 1)

    def test_coding_changes_reasoning_but_not_timing(self):
        loop_modes.set_mode("coding")
        self.assertEqual(loop_modes.reasoning_mode("medium"), "high")
        self.assertEqual(loop_modes.wait_seconds(0, 1), 1)

    def test_unknown_mode_does_not_change_state(self):
        loop_modes.set_mode("claw23")
        self.assertIn("failed", loop_modes.set_mode("unknown"))
        self.assertEqual(loop_modes.current_mode(), "claw23")


if __name__ == "__main__":
    unittest.main()
