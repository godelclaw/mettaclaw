"""Provider routing in synthetic_llm.chat/set_model: synthetic stays the
default path byte-for-byte; claude-* models route to the Anthropic
OpenAI-compatible endpoint with ANTHROPIC_API_KEY; a missing anthropic key
degrades to the empty action instead of raising."""
import io
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import synthetic_llm  # noqa: E402


class FakeResponse(io.BytesIO):
    def __init__(self, payload):
        super().__init__(json.dumps(payload).encode())

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def ok_chat(content="((rest))"):
    return {"choices": [{"message": {"content": content}}]}


class ProviderRoutingTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.flag_dir = tempfile.mkdtemp(prefix="fable-flag-")
        self.flag = os.path.join(self.flag_dir, "fable-enabled")
        self.env = mock.patch.dict(os.environ, {
            "SYNTHETIC_API_KEY": "syn-key",
            "SYNTHETIC_RETRIES": "0",
            "SYNTHETIC_TIMEOUT": "5",
            "ANTHROPIC_ENABLED_FLAG": self.flag,
            "METTACLAW_MODEL_STATE_PATH": os.path.join(
                self.flag_dir, "active-model.txt"),
        }, clear=False)
        self.env.start()
        os.environ.pop("SYNTHETIC_MODEL", None)
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("ANTHROPIC_BASE_URL", None)

    def tearDown(self):
        self.env.stop()

    def enable_flag(self):
        open(self.flag, "w").close()

    def capture_chat(self, model):
        seen = {}

        def fake_urlopen(req, timeout=None):
            seen["url"] = req.full_url
            seen["auth"] = req.headers.get("Authorization")
            seen["body"] = json.loads(req.data)
            return FakeResponse(ok_chat())

        with mock.patch.object(synthetic_llm.urllib.request, "urlopen",
                               fake_urlopen):
            out = synthetic_llm.chat(model, 6000, "medium", "hello")
        return out, seen

    def test_synthetic_default_path_unchanged(self):
        out, seen = self.capture_chat("syn:large:text")
        self.assertEqual(out, "((rest))")
        self.assertEqual(
            seen["url"],
            "https://api.synthetic.new/openai/v1/chat/completions")
        self.assertEqual(seen["auth"], "Bearer syn-key")
        self.assertEqual(seen["body"]["model"], "syn:large:text")

    def test_claude_model_routes_to_native_messages_api(self):
        self.enable_flag()
        os.environ["ANTHROPIC_API_KEY"] = "anth-key"
        os.environ["SYNTHETIC_MODEL"] = "claude-fable-5"
        seen = {}

        def fake_urlopen(req, timeout=None):
            seen["url"] = req.full_url
            seen["key"] = req.headers.get("X-api-key")
            seen["body"] = json.loads(req.data)
            return FakeResponse({"content": [{"type": "text",
                                              "text": "((rest))"}],
                                 "usage": {"input_tokens": 5}})

        with mock.patch.object(synthetic_llm.urllib.request, "urlopen",
                               fake_urlopen):
            out = synthetic_llm.chat(
                "syn:large:text", 6000, "medium",
                "PROMPT: p SKILLS: s LOOPS_LEFT: 5 HISTORY: h")
        self.assertEqual(out, "((rest))")
        self.assertEqual(seen["url"], "https://api.anthropic.com/v1/messages")
        self.assertEqual(seen["key"], "anth-key")
        self.assertEqual(seen["body"]["model"], "claude-fable-5")
        s_block = seen["body"]["system"][0]
        self.assertEqual(s_block["text"], "PROMPT: p SKILLS: s")
        self.assertEqual(s_block["cache_control"], {"type": "ephemeral"})
        self.assertEqual(seen["body"]["messages"][0]["content"],
                         " LOOPS_LEFT: 5 HISTORY: h")

    def test_claude_without_key_returns_empty_action_not_raise(self):
        self.enable_flag()
        os.environ["SYNTHETIC_MODEL"] = "claude-fable-5"
        with mock.patch.object(
                synthetic_llm.urllib.request, "urlopen",
                side_effect=AssertionError("no network call expected")):
            out = synthetic_llm.chat("syn:large:text", 6000, "medium", "hi")
        self.assertEqual(out, "()")

    def test_native_empty_max_tokens_is_diagnosed(self):
        reason = synthetic_llm._diagnose_empty({
            "content": [],
            "stop_reason": "max_tokens",
            "usage": {"output_tokens": 6000},
        })
        self.assertIn("stop_reason=max_tokens", reason)
        self.assertIn("output_tokens=6000", reason)

    def test_set_model_claude_requires_key(self):
        self.enable_flag()
        msg = synthetic_llm.set_model("claude-fable-5")
        self.assertIn("not configured", msg)
        self.assertNotEqual(os.environ.get("SYNTHETIC_MODEL"),
                            "claude-fable-5")

    def test_set_model_claude_with_key_no_network(self):
        self.enable_flag()
        os.environ["ANTHROPIC_API_KEY"] = "anth-key"
        with mock.patch.object(
                synthetic_llm.urllib.request, "urlopen",
                side_effect=AssertionError("no network call expected")):
            msg = synthetic_llm.set_model("claude-fable-5")
        self.assertIn("anthropic", msg)
        self.assertEqual(os.environ["SYNTHETIC_MODEL"], "claude-fable-5")

    def test_set_model_unknown_claude_rejected(self):
        self.enable_flag()
        os.environ["ANTHROPIC_API_KEY"] = "anth-key"
        msg = synthetic_llm.set_model("claude-nonexistent")
        self.assertIn("unknown anthropic model", msg)


    def test_model_choice_persists_across_restart(self):
        import importlib, tempfile, os as _os
        state = _os.path.join(self.flag_dir, "active-model.txt")
        _os.environ["METTACLAW_MODEL_STATE_PATH"] = state
        try:
            _os.environ["ANTHROPIC_API_KEY"] = "anth-key"
            self.enable_flag() if hasattr(self, "enable_flag") else None
            synthetic_llm.set_model("claude-fable-5")
            with open(state, encoding="utf-8") as handle:
                self.assertIn("(active-model claude-fable-5)", handle.read())
            # simulate a restart: boot env sets the config default, then the
            # module import restores the persisted choice
            _os.environ["SYNTHETIC_MODEL"] = "syn:large:text"
            importlib.reload(synthetic_llm)
            self.assertEqual(_os.environ["SYNTHETIC_MODEL"], "claude-fable-5")
        finally:
            _os.environ.pop("METTACLAW_MODEL_STATE_PATH", None)
            importlib.reload(synthetic_llm)


if __name__ == "__main__":
    unittest.main(verbosity=2)
