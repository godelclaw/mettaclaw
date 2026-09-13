"""Provider routing in synthetic_llm.chat/set_model: synthetic stays the
default path byte-for-byte; claude-* models route to the Anthropic
OpenAI-compatible endpoint with ANTHROPIC_API_KEY; a missing anthropic key
degrades to the empty action instead of raising."""
import http.server
import json
import os
import socketserver
import sys
import threading
import time
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import synthetic_llm  # noqa: E402


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
            "SYNTHETIC_EMPTY_BACKOFF": "0",
            "ANTHROPIC_ENABLED_FLAG": self.flag,
            "METTACLAW_MODEL_STATE_PATH": os.path.join(
                self.flag_dir, "active-model.txt"),
            "METTACLAW_COGNITIVE_HEALTH_PATH": os.path.join(
                self.flag_dir, "cognitive-health.json"),
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

        def fake_request_json(req, timeout=None):
            seen["url"] = req.full_url
            seen["auth"] = req.headers.get("Authorization")
            seen["body"] = json.loads(req.data)
            return ok_chat()

        with mock.patch.object(synthetic_llm, "_request_json",
                               fake_request_json):
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
        health = synthetic_llm.cognitive_health.snapshot()
        self.assertEqual(health["completed_count"], 1)
        self.assertEqual(health["pending_since"], 0)

    def test_claude_model_routes_to_native_messages_api(self):
        self.enable_flag()
        os.environ["ANTHROPIC_API_KEY"] = "anth-key"
        os.environ["SYNTHETIC_MODEL"] = "claude-fable-5"
        seen = {}

        def fake_request_json(req, timeout=None):
            seen["url"] = req.full_url
            seen["key"] = req.headers.get("X-api-key")
            seen["body"] = json.loads(req.data)
            return {"content": [{"type": "text", "text": "((rest))"}],
                    "usage": {"input_tokens": 5}}

        with mock.patch.object(synthetic_llm, "_request_json",
                               fake_request_json):
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
                synthetic_llm, "_request_json",
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

    def test_one_cognitive_turn_never_hides_replacement_requests(self):
        os.environ["SYNTHETIC_RETRIES"] = "99"
        calls = []

        def unavailable(_request, timeout=None):
            calls.append(timeout)
            raise urllib.error.URLError("temporarily unavailable")

        with mock.patch.object(
                synthetic_llm, "_request_json", unavailable):
            out = synthetic_llm.chat(
                "syn:large:text", 6000, "medium", "hello")

        self.assertEqual(out, "()")
        self.assertEqual(len(calls), 1)

    def test_nonretriable_http_error_remains_inside_provider_boundary(self):
        failure = urllib.error.HTTPError(
            "https://provider.invalid/chat", 404, "model retired", {}, None)
        with mock.patch.object(
                synthetic_llm, "_request_json", side_effect=failure):
            out = synthetic_llm.chat(
                "retired-model", 6000, "medium", "hello")
        self.assertEqual(out, "()")
        health = synthetic_llm.cognitive_health.snapshot()
        self.assertEqual(health["last_failure_type"], "httperror")

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
                synthetic_llm, "_request_json",
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


class FakeHTTPResponse:
    def __init__(self, payload=b"{}", status=200, reason="OK",
                 headers=None, read_error=None):
        self.payload = payload
        self.status = status
        self.reason = reason
        self.headers = {} if headers is None else headers
        self.read_error = read_error

    def read(self):
        if self.read_error is not None:
            raise self.read_error
        return self.payload


class FakeConnection:
    def __init__(self, response=None, request_error=None,
                 response_error=None):
        self.response = response or FakeHTTPResponse()
        self.request_error = request_error
        self.response_error = response_error
        self.close_count = 0
        self.request_args = None

    def request(self, *args, **kwargs):
        self.request_args = (args, kwargs)
        if self.request_error is not None:
            raise self.request_error

    def getresponse(self):
        if self.response_error is not None:
            raise self.response_error
        return self.response

    def close(self):
        self.close_count += 1


class ProviderResourceLifetimeTest(unittest.TestCase):
    def request(self):
        return synthetic_llm.urllib.request.Request(
            "https://provider.invalid/v1/chat?trace=yes",
            b'{"hello":"world"}',
            {"Authorization": "Bearer test"},
        )

    def run_with(self, connection):
        with mock.patch.object(
                synthetic_llm, "_open_connection",
                return_value=connection):
            return synthetic_llm._request_json(self.request(), 1.0)

    def test_success_closes_connection_exactly_once(self):
        connection = FakeConnection(FakeHTTPResponse(b'{"ok":true}'))
        self.assertEqual(self.run_with(connection), {"ok": True})
        self.assertEqual(connection.close_count, 1)
        args, kwargs = connection.request_args
        self.assertEqual(args[:2], ("POST", "/v1/chat?trace=yes"))
        self.assertEqual(kwargs["body"], b'{"hello":"world"}')

    def test_request_timeout_closes_connection_exactly_once(self):
        connection = FakeConnection(request_error=TimeoutError("connect"))
        with self.assertRaises(TimeoutError):
            self.run_with(connection)
        self.assertEqual(connection.close_count, 1)

    def test_response_timeout_closes_connection_exactly_once(self):
        connection = FakeConnection(response_error=TimeoutError("headers"))
        with self.assertRaises(TimeoutError):
            self.run_with(connection)
        self.assertEqual(connection.close_count, 1)

    def test_read_timeout_closes_connection_exactly_once(self):
        response = FakeHTTPResponse(read_error=TimeoutError("body"))
        connection = FakeConnection(response)
        with self.assertRaises(TimeoutError):
            self.run_with(connection)
        self.assertEqual(connection.close_count, 1)

    def test_http_error_closes_connection_exactly_once(self):
        connection = FakeConnection(FakeHTTPResponse(
            b'{"error":"busy"}', status=429, reason="Too Many Requests"))
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.run_with(connection)
        self.assertEqual(raised.exception.code, 429)
        self.assertEqual(connection.close_count, 1)

    def test_decode_error_closes_connection_exactly_once(self):
        connection = FakeConnection(FakeHTTPResponse(b"not-json"))
        with self.assertRaises(json.JSONDecodeError):
            self.run_with(connection)
        self.assertEqual(connection.close_count, 1)

    def test_retained_real_timeouts_do_not_retain_descriptors(self):
        if not os.path.isdir("/proc/self/fd"):
            self.skipTest("descriptor census requires procfs")

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        class SlowHeaders(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("content-length", "0"))
                if length:
                    self.rfile.read(length)
                time.sleep(0.05)

            def log_message(self, *_args):
                pass

        server = Server(("127.0.0.1", 0), SlowHeaders)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        baseline = len(os.listdir("/proc/self/fd"))
        retained = []
        request = synthetic_llm.urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/chat",
            b"{}",
            {"Content-Type": "application/json"},
        )
        try:
            for _ in range(32):
                try:
                    synthetic_llm._request_json(request, 0.01)
                except TimeoutError as exc:
                    # Keep every traceback alive. Descriptor safety must come
                    # from the explicit finalizer, never eventual GC.
                    retained.append(exc)
            time.sleep(0.1)
            after = len(os.listdir("/proc/self/fd"))
            self.assertEqual(len(retained), 32)
            self.assertLessEqual(after, baseline)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
