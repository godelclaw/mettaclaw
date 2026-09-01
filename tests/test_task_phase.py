import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import task_phase  # noqa: E402


class TaskPhaseTests(unittest.TestCase):
    def test_completed_phase_cannot_silently_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "phase.json"
            with mock.patch.dict(os.environ, {
                "METTACLAW_TASK_PHASE_PATH": str(path),
            }):
                task_phase.initialize("task-1", ("inspect", "test"))
                self.assertEqual(
                    task_phase.transition("inspect", "active", "r1"),
                    "PHASE_ADVANCED",
                )
                self.assertEqual(
                    task_phase.transition(
                        "inspect", "completed", "r2", "receipt-1"
                    ),
                    "PHASE_ADVANCED",
                )
                self.assertEqual(
                    task_phase.transition("inspect", "active", "r3"),
                    "WITHHELD_PHASE_REGRESSION",
                )
                state = task_phase.snapshot()
                self.assertEqual(
                    state["phases"]["inspect"],
                    {"status": "completed", "evidence": "receipt-1"},
                )
                self.assertIn("completed=[\"inspect\"]", task_phase.view())

    def test_completion_requires_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "phase.json"
            task_phase.initialize("task-1", path=path)
            with self.assertRaisesRegex(ValueError, "evidence reference"):
                task_phase.transition(
                    "inspect", "completed", "r1", path=path
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
