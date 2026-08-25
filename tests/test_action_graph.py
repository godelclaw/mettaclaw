import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import action_graph  # noqa: E402


class ActionGraphTests(unittest.TestCase):
    def test_unknown_action_remains_permitted_without_fake_certificate(self):
        node = action_graph.classify(["future-skill", "argument"])
        self.assertEqual(node.kind, "unspecified")
        self.assertTrue(action_graph.coordination_admitted(node, ()))

    def test_new_stimulus_keeps_only_broker_known_observation(self):
        independent, dependent = action_graph.partition_after_stimulus((
            ["future-skill"], ["tmux-windows"],
            ["tmux-send-observed", "r1", "yes"],
        ))
        self.assertEqual(independent, [["tmux-windows"]])
        self.assertEqual(dependent, [
            ["future-skill"], ["tmux-send-observed", "r1", "yes"]
        ])

    def test_coordination_requires_a_current_observation_receipt(self):
        node = action_graph.classify(["tmux-send-observed", "r1", "yes"])
        self.assertEqual(node.kind, "coordination")
        self.assertFalse(action_graph.coordination_admitted(node, ()))
        self.assertTrue(action_graph.coordination_admitted(node, ("r1",)))

    def test_disjoint_exact_panes_certify_a_chain(self):
        left = action_graph.classify(
            ["tmux-send-observed", "r1", ":"], 0
        )
        right = action_graph.classify(
            ["tmux-send-observed", "r2", ":"], 1
        )
        self.assertTrue(action_graph.certified_chain(
            left, right, {"r1": "%1", "r2": "%2"}
        ))
        self.assertFalse(action_graph.certified_chain(
            left, right, {"r1": "%1", "r2": "%1"}
        ))


if __name__ == "__main__":
    unittest.main(verbosity=2)
