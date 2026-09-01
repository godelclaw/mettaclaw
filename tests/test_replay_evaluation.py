import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import replay_evaluation  # noqa: E402


class ReplayEvaluationTests(unittest.TestCase):
    def test_historical_pattern_and_certified_replay_are_distinguished(self):
        fixtures = ROOT / "tests" / "fixtures"
        before = replay_evaluation.evaluate_file(
            fixtures / "godel_tmux_history_before.json"
        )
        repaired = replay_evaluation.evaluate_file(
            fixtures / "godel_tmux_history_certified.json"
        )
        self.assertEqual(before.redundant_effects, 1)
        self.assertEqual(before.stale_state_actions, 1)
        self.assertEqual(before.lost_commitments, 1)
        self.assertEqual(before.unsupported_claims, 1)
        self.assertEqual(before.evidence_recovery_success, 1 / 3)
        self.assertEqual(before.operator_interruption_latency_ms, 150)
        self.assertEqual(repaired.redundant_effects, 0)
        self.assertEqual(repaired.stale_state_actions, 0)
        self.assertEqual(repaired.lost_commitments, 0)
        self.assertEqual(repaired.unsupported_claims, 0)
        self.assertEqual(repaired.evidence_recovery_success, 1)
        self.assertEqual(repaired.operator_interruption_latency_ms, 2)
        self.assertLess(repaired.context_chars_max, before.context_chars_max)


if __name__ == "__main__":
    unittest.main(verbosity=2)
