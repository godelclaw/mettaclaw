"""Focused tests for the NEW-ACTIVITY batch drain (context-centric turns).

Covers exactly the review's four cases: chronological single drain, mixed
human/bot routing+tier from the newest human, bot-only batches without
human arming, and the empty second drain being not-new (non-emptiness is
the newness test in the loop)."""
import os
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, os.path.join(ROOT, "channels"))
import telegram


def _reset():
    with telegram._msg_lock:
        del telegram._pending_messages[:]
        telegram._activity_epoch = 0
        telegram._context_activity_epoch = 0
        telegram._reply_chat_id = ""
        telegram._last_message_is_human = False
        telegram._last_from_bot = False
        telegram._last_arm_tier = "full"
    with telegram._effect_lock:
        telegram._effect_turn = None
        telegram._effect_activity_epoch = None


class ActivityBatchTests(unittest.TestCase):
    def setUp(self):
        _reset()
        self.lifecycle = mock.patch("lifecycle.cognition_enabled",
                                    return_value=1)
        self.lifecycle.start()
        self.addCleanup(self.lifecycle.stop)

    def test_batch_drains_all_chronologically(self):
        telegram._set_last("1", "first", from_bot=False, arm_tier="full")
        telegram._set_last("1", "second", from_bot=True)
        telegram._set_last("1", "third", from_bot=False, arm_tier="mid")
        batch = telegram.getActivityBatch()
        self.assertEqual(batch.splitlines(), ["first", "second", "third"])
        with telegram._msg_lock:
            self.assertFalse(telegram._pending_messages)

    def test_mixed_batch_routes_and_arms_from_newest_human(self):
        telegram._set_last("7", "human-early", from_bot=False,
                           arm_tier="mid")
        telegram._set_last("9", "bot-later", from_bot=True)
        telegram.getActivityBatch()
        self.assertEqual(telegram._reply_chat_id, "7")
        self.assertEqual(telegram.lastMessageIsHuman(), 1)
        self.assertEqual(telegram.lastMessageArmLoops(),
                         telegram._tier_loops("mid"))

    def test_bot_only_batch_does_not_arm_as_human(self):
        telegram._set_last("5", "bot-a", from_bot=True)
        telegram._set_last("5", "bot-b", from_bot=True)
        batch = telegram.getActivityBatch()
        self.assertIn("bot-a", batch)
        self.assertIn("bot-b", batch)
        self.assertEqual(telegram._reply_chat_id, "5")
        self.assertEqual(telegram.lastMessageIsHuman(), 0)

    def test_second_drain_is_empty_hence_not_new(self):
        telegram._set_last("1", "only", from_bot=False)
        self.assertEqual(telegram.getActivityBatch(), "only")
        self.assertEqual(telegram.getActivityBatch(), "")
        self.assertEqual(telegram.lastMessageIsHuman(), 0)

    def test_new_stimulus_invalidates_the_captured_effect_frontier(self):
        telegram._set_last("1", "in prompt", from_bot=False)
        self.assertEqual(telegram.getActivityBatch(), "in prompt")
        telegram.begin_effect_turn("turn-1")
        self.assertEqual(telegram.effect_turn_stimulus_free("turn-1"), 1)
        telegram._set_last("1", "arrived during work", from_bot=False)
        self.assertEqual(telegram.effect_turn_stimulus_free("turn-1"), 0)

    def test_reentry_does_not_launder_a_new_stimulus_into_old_turn(self):
        telegram.getActivityBatch()
        telegram.begin_effect_turn("turn-1")
        telegram._set_last("1", "new", from_bot=False)
        telegram.begin_effect_turn("turn-1")
        self.assertEqual(telegram.effect_turn_stimulus_free("turn-1"), 0)

    def test_operator_revocation_interrupts_the_unexecuted_suffix(self):
        telegram.getActivityBatch()
        telegram.begin_effect_turn("turn-stop")
        with mock.patch("lifecycle.cognition_enabled", return_value=1):
            self.assertEqual(
                telegram.effect_turn_stimulus_free("turn-stop"), 1)
        with mock.patch("lifecycle.cognition_enabled", return_value=0):
            self.assertEqual(
                telegram.effect_turn_stimulus_free("turn-stop"), 0)

    def test_loop_derives_newness_from_nonempty_batch(self):
        loop = (ROOT / "src" / "loop.metta").read_text(encoding="utf-8")
        self.assertIn('($message (eval (receive)))', loop)
        self.assertIn(
            '($hasActivity\n            (== (py-call (helper.text_nonempty $message)) 1))',
            loop)
        self.assertNotIn(
            "($msgnew (prog1 (!= $msg (get-state &prevmsg))", loop)

    def test_iter_renews_only_after_an_idle_wait(self):
        loop = (ROOT / "src" / "loop.metta").read_text(encoding="utf-8")
        policy = (ROOT / "src" / "loop_policy.metta").read_text(
            encoding="utf-8")
        self.assertIn("(processLoop (initLoop))", loop)
        self.assertIn("(loop-autonomous-ready $periphery)", loop)
        self.assertIn("(policy-wait-seconds", policy)
        self.assertIn("(policy-next-autonomous-ready", policy)
        self.assertIn("AUTONOMOUS_POLICY_BURST", loop)
        self.assertIn("cognitive_health.expect_turn", loop)
        self.assertNotIn("telegram.getMode", loop)

    def test_lifecycle_gate_is_outside_the_enabled_turn(self):
        loop = (ROOT / "src" / "loop.metta").read_text(encoding="utf-8")
        enabled_definition = loop.index("(= (enabledTurnCandidate $periphery)")
        receive = loop.index("($message (eval (receive)))", enabled_definition)
        wrapper = loop.index("(= (turnCandidate $periphery)")
        gate = loop.index("(lifecycle.cognition_enabled)", wrapper)
        enabled_call = loop.index("(enabledTurnCandidate $periphery)", gate)
        self.assertLess(enabled_definition, receive)
        self.assertLess(wrapper, gate)
        self.assertLess(gate, enabled_call)
        self.assertIn("(if $enabled\n                (applyTimedContinuation",
                      loop)

    def test_attention_graph_brackets_the_model_action(self):
        loop = (ROOT / "src" / "loop.metta").read_text(encoding="utf-8")
        begin = loop.index("(attention-begin")
        model = loop.index("(addition-model-call")
        complete = loop.index("(attention-complete")
        self.assertLess(begin, model)
        self.assertLess(model, complete)

    def test_model_call_is_committed_before_response_parsing(self):
        loop = (ROOT / "src" / "loop.metta").read_text(encoding="utf-8")
        model = loop.index("(addition-model-call")
        commitment = loop.index("($_ (cut))", model)
        parse = loop.index("(addition-read-response", model)
        self.assertLess(model, commitment)
        self.assertLess(commitment, parse)
        pipeline = (ROOT / "src" / "command_pipeline.metta").read_text(
            encoding="utf-8"
        )
        self.assertIn("(sread", pipeline)
        self.assertIn("((Error $a $b) ())", pipeline)

    def test_commands_cross_one_committed_effect_boundary(self):
        loop = (ROOT / "src" / "loop.metta").read_text(encoding="utf-8")
        response = loop.index("(RESPONSE: $sexpr)")
        commitment = loop.index("($_ (cut))", response)
        dispatcher = loop.index("(addition-effect-broker", response)
        results = loop.index("($results (RESULTS:", response)
        self.assertLess(response, commitment)
        self.assertLess(commitment, dispatcher)
        self.assertLess(dispatcher, results)
        self.assertIn(
            "(policy-command-batch-limit (loop-active-policy $periphery))",
            loop[dispatcher:results],
        )
        self.assertNotIn("run-command-batch-once $iteration $sexpr", loop)
        self.assertNotIn("(collapse (let $s (superpose $sexpr)", loop)
        frontier = loop.index("(addition-effect-turn-begin $iteration)")
        self.assertLess(frontier, response)
        self.assertNotIn("(telegram.begin_effect_turn", loop)


if __name__ == "__main__":
    unittest.main()
