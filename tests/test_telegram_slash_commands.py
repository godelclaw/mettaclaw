"""Deterministic slash commands (/model, /models, /quota) are answered in the
poll thread with zero LLM involvement and are never queued for the agent."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "channels"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import telegram  # noqa: E402
import synthetic_llm  # noqa: E402


class SlashCommandTest(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.p1 = mock.patch.object(
            telegram, "send_message_to_chat",
            lambda chat_id, text: self.sent.append((chat_id, text)))
        self.p1.start()
        self.p2 = mock.patch.object(
            synthetic_llm, "model_ids", lambda: ["modelA", "modelB"])
        self.p3 = mock.patch.object(
            synthetic_llm, "quota", lambda: "model=x | weekly=ok")
        self.p4 = mock.patch.object(
            synthetic_llm, "set_model",
            lambda name: f"model set to '{name}'")
        self.p5 = mock.patch.object(
            synthetic_llm, "current_model", lambda: "syn:large:text")
        for p in (self.p2, self.p3, self.p4, self.p5):
            p.start()
        self.chat = {"id": -4321}
        self.operator = {"id": 111000111}
        os.environ["METTACLAW_TELEGRAM_OPERATOR_IDS"] = "111000111"

    def tearDown(self):
        for p in (self.p1, self.p2, self.p3, self.p4, self.p5):
            p.stop()

    def handle(self, text, sender=None):
        return telegram._handle_slash_command(
            self.chat, self.operator if sender is None else sender, text)

    def test_non_operator_passthrough(self):
        self.assertIsNone(self.handle("/model claude-fable-5",
                                      sender={"id": 42}))
        self.assertEqual(self.sent, [])

    def test_models_sends_keyboard(self):
        posts = []
        with mock.patch.object(telegram.requests, "post",
                               lambda url, json=None, timeout=None:
                               posts.append((url, json)) or mock.Mock()):
            self.assertEqual(self.handle("/models"), "slash_command:/models")
        url, payload = posts[-1]
        self.assertIn("sendMessage", url)
        kb = payload["reply_markup"]["inline_keyboard"]
        self.assertEqual([r[0]["callback_data"] for r in kb],
                         ["model:modelA", "model:modelB"])

    def test_callback_switches_model(self):
        posts = []
        cq = {"id": "77", "data": "model:modelB", "from": {"id": 111000111},
              "message": {"message_id": 5, "chat": {"id": -4321}}}
        with mock.patch.object(telegram, "_chat_is_allowed",
                               lambda chat: True), \
             mock.patch.object(telegram.requests, "post",
                               lambda url, json=None, timeout=None:
                               posts.append((url, json)) or mock.Mock()):
            note = telegram._handle_callback_query(cq)
        self.assertEqual(note, "callback_model_switch")
        self.assertTrue(any("answerCallbackQuery" in u for u, _ in posts))
        self.assertTrue(any("editMessageText" in u for u, _ in posts))

    def test_callback_disallowed_chat_ignored(self):
        cq = {"id": "78", "data": "model:modelB", "from": {"id": 111000111},
              "message": {"message_id": 5, "chat": {"id": 999}}}
        with mock.patch.object(telegram, "_chat_is_allowed",
                               lambda chat: False):
            self.assertEqual(telegram._handle_callback_query(cq),
                             "callback_disallowed_chat")

    def test_quota(self):
        self.assertEqual(self.handle("/quota"), "slash_command:/quota")
        self.assertIn("weekly=ok", self.sent[-1][1])

    def test_model_bare_shows_current(self):
        self.assertEqual(self.handle("/model"), "slash_command:/model")
        self.assertIn("syn:large:text", self.sent[-1][1])

    def test_model_switch(self):
        self.assertEqual(self.handle("/model claude-fable-5"),
                         "slash_command:/model")
        self.assertIn("claude-fable-5", self.sent[-1][1])

    def test_botname_suffix_for_self_is_handled(self):
        telegram._bot_username = "SomeBot"
        try:
            self.assertEqual(self.handle("/models@SomeBot"),
                             "slash_command:/models")
        finally:
            telegram._bot_username = None

    def test_botname_suffix_for_other_bot_is_consumed(self):
        telegram._bot_username = "SomeBot"
        try:
            self.assertEqual(self.handle("/models@OtherBot"),
                             "slash_command_other_bot:otherbot")
        finally:
            telegram._bot_username = None

    def test_unrelated_commands_and_text_pass_through(self):
        self.assertIsNone(self.handle("/start"))
        self.assertIsNone(self.handle("hello there"))
        self.assertIsNone(self.handle(""))
        self.assertEqual(len(self.sent), 0)

    def test_handler_error_never_raises(self):
        with mock.patch.object(synthetic_llm, "model_ids",
                               side_effect=RuntimeError("boom")):
            note = self.handle("/models")
        self.assertEqual(note, "slash_command_error:/models")



class CrossBotAddressingTests(unittest.TestCase):
    def setUp(self):
        telegram._bot_username = "LilaTestBot"

    def tearDown(self):
        telegram._bot_username = None

    def test_command_for_another_bot_is_consumed_not_answered(self):
        note = telegram._handle_slash_command(
            {"id": 1}, {"id": 111000111}, "/model@GodelOruziBot")
        self.assertEqual(note, "slash_command_other_bot:godeloruzibot")

    def test_unknown_identity_with_suffix_is_consumed(self):
        telegram._bot_username = None
        with mock.patch.object(telegram, "requests") as req:
            req.get.side_effect = Exception("net down")
            note = telegram._handle_slash_command(
                {"id": 1}, {"id": 111000111}, "/model@AnyBot")
        self.assertEqual(note, "slash_command_other_bot:anybot")


if __name__ == "__main__":
    unittest.main(verbosity=2)
