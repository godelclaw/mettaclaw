"""Focused tests for the NEW-ACTIVITY batch drain (context-centric turns).

Covers exactly the review's four cases: chronological single drain, mixed
human/bot routing+tier from the newest human, bot-only batches without
human arming, and the empty second drain being not-new (non-emptiness is
the newness test in the loop)."""
import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, os.path.join(ROOT, "channels"))
import telegram


def _reset():
    with telegram._msg_lock:
        del telegram._pending_messages[:]
        telegram._reply_chat_id = ""
        telegram._last_message_is_human = False
        telegram._last_from_bot = False
        telegram._last_arm_tier = "full"


class ActivityBatchTests(unittest.TestCase):
    def setUp(self):
        _reset()

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

    def test_loop_derives_newness_from_nonempty_batch(self):
        loop = (ROOT / "src" / "loop.metta").read_text(encoding="utf-8")
        self.assertIn("($msgnew (> (string_length $msg) 0))", loop)
        self.assertNotIn(
            "($msgnew (prog1 (!= $msg (get-state &prevmsg))", loop)

    def test_claw23_renews_only_after_an_idle_wait(self):
        loop = (ROOT / "src" / "loop.metta").read_text(encoding="utf-8")
        self.assertIn("(mettaclaw 1 0)", loop)
        self.assertIn("(== $autonomousReady 1)", loop)
        self.assertIn("loop_modes.wait_seconds", loop)
        self.assertIn("loop_modes.autonomous_ready", loop)
        self.assertIn("CLAW23_AUTONOMOUS_BURST", loop)
        self.assertIn("cognitive_health.expect_turn", loop)
        self.assertNotIn("telegram.getMode", loop)

    def test_attention_graph_brackets_the_model_action(self):
        loop = (ROOT / "src" / "loop.metta").read_text(encoding="utf-8")
        begin = loop.index("(attention-begin")
        model = loop.index("(synthetic_llm.chat")
        complete = loop.index("(attention-complete")
        self.assertLess(begin, model)
        self.assertLess(model, complete)


if __name__ == "__main__":
    unittest.main()
