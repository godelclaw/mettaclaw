import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import process_host  # noqa: E402


FIXTURES = Path(__file__).with_name("fixtures")
PERIPHERY = [
    "three-policy-periphery",
    "development-0",
    "life-0",
    "coding-0",
    "agent",
]


class ProcessHostTests(unittest.TestCase):
    def test_success_returns_candidate_periphery(self):
        outcome = process_host.invoke(
            str(FIXTURES / "process_replace.py"), PERIPHERY
        )
        self.assertEqual(
            outcome,
            [
                1,
                [
                    "three-policy-periphery",
                    "development-new",
                    "life-new",
                    "coding-new",
                    "iter",
                ],
            ],
        )

    def test_exception_becomes_failure(self):
        outcome = process_host.invoke(str(FIXTURES / "process_fail.py"), PERIPHERY)
        self.assertEqual(outcome[0], 0)
        self.assertIn("RuntimeError", outcome[1])

    def test_missing_process_becomes_failure(self):
        outcome = process_host.invoke(str(FIXTURES / "missing.py"), PERIPHERY)
        self.assertEqual(outcome[0], 0)
        self.assertIn("resolution failed", outcome[1])

    def test_timeout_becomes_failure(self):
        with patch.dict(
            os.environ, {"THREE_POLICY_PROCESS_TIMEOUT_SECONDS": "0.05"}
        ):
            outcome = process_host.invoke(
                str(FIXTURES / "process_timeout.py"), PERIPHERY
            )
        self.assertEqual(outcome, [0, "TIMEOUT"])


if __name__ == "__main__":
    unittest.main()
