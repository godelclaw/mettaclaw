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

    def test_failed_delete_withholds_dependent_suffix(self):
        self.assertFalse(action_graph.result_permits_dependent_suffix(
            ["delete-my-recent", "research-group", 3],
            "no recorded own-sends to chat research-group — nothing to delete",
        ))
        self.assertFalse(action_graph.result_permits_dependent_suffix(
            ["send-telegram-chat", "research-group", "report"],
            "send failed: target chat is not allowed",
        ))
        self.assertFalse(action_graph.result_permits_dependent_suffix(
            ["delete-message-exact", "research-group", 42],
            "delete failed: message not found",
        ))

    def test_successful_or_unrelated_effect_remains_permissive(self):
        self.assertTrue(action_graph.result_permits_dependent_suffix(
            ["delete-my-recent", "research-group", 2],
            "deleted message 43 from chat x | "
            "deleted message 42 from chat x",
        ))
        self.assertTrue(action_graph.result_permits_dependent_suffix(
            ["future-skill"], "anything",
        ))
        self.assertTrue(action_graph.result_permits_dependent_suffix(
            ["send", "report"], "sent message 9 to chat private",
        ))


if __name__ == "__main__":
    unittest.main(verbosity=2)
