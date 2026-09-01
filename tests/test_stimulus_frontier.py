"""Cross-runtime stimulus frontier stays tiny, atomic, and fail-closed."""

import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(ROOT / "src"))

import stimulus_frontier  # noqa: E402


class StimulusFrontierTest(unittest.TestCase):
    def test_matching_epoch_is_free_and_newer_epoch_interrupts(self):
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / "frontier"
            with mock.patch.dict(os.environ, {
                "METTACLAW_STIMULUS_FRONTIER_PATH": os.fspath(target),
            }):
                self.assertTrue(stimulus_frontier.publish(7, 3, 3))
                self.assertEqual(stimulus_frontier.read(), (7, 3, 3))
                self.assertEqual(stimulus_frontier.stimulus_free(7), 1)
                stimulus_frontier.publish(7, 3, 4)
                self.assertEqual(stimulus_frontier.stimulus_free(7), 0)

    def test_wrong_turn_and_malformed_record_are_not_free(self):
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / "frontier"
            with mock.patch.dict(os.environ, {
                "METTACLAW_STIMULUS_FRONTIER_PATH": os.fspath(target),
            }):
                stimulus_frontier.publish(7, 3, 3)
                self.assertEqual(stimulus_frontier.stimulus_free(8), 0)
                target.write_text("not a frontier\n", encoding="ascii")
                self.assertIsNone(stimulus_frontier.read())
                self.assertEqual(stimulus_frontier.stimulus_free(7), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
