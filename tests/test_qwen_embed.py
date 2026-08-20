#!/usr/bin/env python3
import importlib
import json
import os
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False


def load_module():
    os.environ["METTACLAW_EMBED_ENDPOINT"] = "http://127.0.0.1:8876"
    os.environ["METTACLAW_EMBED_DIM"] = "3"
    os.environ["METTACLAW_EMBED_PROTOCOL"] = "test-protocol"
    import qwen_embed

    return importlib.reload(qwen_embed)


def test_remote_embedding_contract():
    module = load_module()
    module.urllib.request.urlopen = lambda _req, timeout: FakeResponse(
        {"embeddings": [[0.1, 0.2, 0.3]], "dim": 3, "protocol": "test-protocol"}
    )
    assert module.embed_query("hello") == [0.1, 0.2, 0.3]


def test_remote_embedding_rejects_protocol_drift():
    module = load_module()
    module.urllib.request.urlopen = lambda _req, timeout: FakeResponse(
        {"embeddings": [[0.1, 0.2, 0.3]], "dim": 3, "protocol": "other"}
    )
    try:
        module.embed_document("hello")
    except RuntimeError as exc:
        assert "protocol mismatch" in str(exc)
    else:
        raise AssertionError("protocol drift was accepted")


def test_guarded_ops_report_daemon_down_as_result():
    module = load_module()

    def refuse(_req, timeout):
        raise OSError("connection refused")

    module.urllib.request.urlopen = refuse
    q = module.query_guarded("anything", 5)
    r = module.remember_guarded("anything", "2026-07-18")
    assert q.startswith("EMBED_DAEMON_DOWN") and "infer absence" in q
    assert r.startswith("EMBED_DAEMON_DOWN") and "NOT saved" in r


def test_guarded_ops_reraise_non_daemon_errors():
    module = load_module()
    module.urllib.request.urlopen = lambda _req, timeout: FakeResponse(
        {"embeddings": [[0.1, 0.2, 0.3]], "dim": 3, "protocol": "other"}
    )
    try:
        module.query_guarded("anything", 5)
    except RuntimeError as exc:
        assert "protocol mismatch" in str(exc)
    else:
        raise AssertionError("non-daemon error was swallowed")


if __name__ == "__main__":
    test_remote_embedding_contract()
    test_remote_embedding_rejects_protocol_drift()
    test_guarded_ops_report_daemon_down_as_result()
    test_guarded_ops_reraise_non_daemon_errors()
