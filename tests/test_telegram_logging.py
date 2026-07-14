#!/usr/bin/env python3
import importlib
import json
import os
import pathlib
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_telegram():
    from channels import telegram

    return importlib.reload(telegram)


class FakeResponse:
    def __init__(self, payload=None, chunks=()):
        self.payload = payload
        self.chunks = chunks

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload

    def iter_content(self, _size):
        return iter(self.chunks)

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False


def test_poll_logs_before_advancing_offset_and_queues_allowed_message():
    tg = load_telegram()
    updates = [
        {
            "update_id": 100,
            "message": {
                "message_id": 10,
                "chat": {"id": -1, "type": "group", "title": "Allowed Group"},
                "from": {"id": 42, "username": "zar"},
                "text": "hello from allowed",
            },
        },
        {
            "update_id": 101,
            "message": {
                "message_id": 11,
                "chat": {"id": -2, "type": "group", "title": "Other Group"},
                "from": {"id": 43, "username": "stranger"},
                "text": "private to other group",
                "document": {"file_id": "must-not-download"},
            },
        },
    ]

    def fake_get(url, params=None, timeout=None):
        assert url.endswith("/getUpdates")
        tg._running = False
        return FakeResponse({"ok": True, "result": updates})

    with tempfile.TemporaryDirectory() as tmp:
        tg.requests.get = fake_get
        tg._token = "fake-token"
        tg._allowed_chat_ids = {"-1"}
        tg._allow_private_chats = False
        tg._offset = None
        tg._offset_path = str(pathlib.Path(tmp) / "offset.txt")
        tg._log_path = str(pathlib.Path(tmp) / "telegram_updates.jsonl")
        tg._pending_messages = []
        tg._reply_chat_id = ""
        tg._last_chat_id = ""
        tg._running = True

        tg._poll_loop()

        records = [
            json.loads(line)
            for line in pathlib.Path(tg._log_path).read_text(encoding="utf-8").splitlines()
        ]
        assert [record["update_id"] for record in records] == [100, 101]
        assert pathlib.Path(tg._offset_path).read_text(encoding="utf-8") == "102"

        allowed = records[0]
        assert allowed["allowed"] is True
        assert allowed["queued"] is True
        assert allowed["chat_id"] == "-1"
        assert allowed["message_id"] == 10
        assert allowed["from_id"] == "42"
        assert allowed["text"] == "hello from allowed"
        assert allowed["raw"]["message"]["text"] == "hello from allowed"

        disallowed = records[1]
        assert disallowed["allowed"] is False
        assert disallowed["queued"] is False
        assert disallowed["note"] == "disallowed_chat"
        assert disallowed["chat_id"] == "-2"
        assert disallowed["text"] is None
        assert disallowed["raw"] is None

        queued = tg.getLastMessage()
        assert 'update_id="100"' in queued
        assert 'chat_id="-1"' in queued
        assert 'message_id="10"' in queued
        assert 'from_id="42"' in queued
        assert "hello from allowed" in queued
        assert "private to other group" not in queued


def test_channel_posts_are_logged_with_kind():
    tg = load_telegram()
    with tempfile.TemporaryDirectory() as tmp:
        tg._log_path = str(pathlib.Path(tmp) / "telegram_updates.jsonl")
        update = {
            "update_id": 200,
            "channel_post": {
                "message_id": 20,
                "chat": {"id": -100, "type": "channel", "title": "News"},
                "text": "channel text",
            },
        }
        kind, message = tg._extract_message(update)
        assert kind == "channel_post"
        assert tg._append_update_log(update, kind, message, True, True, "")
        record = json.loads(pathlib.Path(tg._log_path).read_text(encoding="utf-8"))
        assert record["kind"] == "channel_post"
        assert record["chat_id"] == "-100"
        assert record["raw"]["channel_post"]["text"] == "channel text"


def test_log_failure_does_not_block_message_delivery_or_offset():
    tg = load_telegram()
    update = {
        "update_id": 300,
        "message": {
            "message_id": 30,
            "chat": {"id": -1, "type": "group", "title": "Allowed Group"},
            "from": {"id": 42, "username": "zar"},
            "text": "deliver even if logging fails",
        },
    }

    def fake_get(url, params=None, timeout=None):
        tg._running = False
        return FakeResponse({"ok": True, "result": [update]})

    with tempfile.TemporaryDirectory() as tmp:
        tg.requests.get = fake_get
        tg._append_update_log = lambda *args, **kwargs: False
        tg._token = "fake-token"
        tg._allowed_chat_ids = {"-1"}
        tg._allow_private_chats = False
        tg._offset = None
        tg._offset_path = str(pathlib.Path(tmp) / "offset.txt")
        tg._pending_messages = []
        tg._reply_chat_id = ""
        tg._last_chat_id = ""
        tg._running = True

        tg._poll_loop()

        assert pathlib.Path(tg._offset_path).read_text(encoding="utf-8") == "301"
        queued = tg.getLastMessage()
        assert 'update_id="300"' in queued
        assert "deliver even if logging fails" in queued


def test_attachment_download_is_atomic_and_sanitized():
    tg = load_telegram()
    message = {
        "message_id": 7,
        "document": {
            "file_id": "file-1",
            "file_name": "../../bad name.pdf",
            "mime_type": "application/pdf",
            "file_size": 6,
        },
    }

    def fake_get(url, params=None, timeout=None, stream=False):
        if url.endswith("/getFile"):
            assert params == {"file_id": "file-1"}
            return FakeResponse({"ok": True, "result": {"file_path": "docs/server.pdf"}})
        assert stream is True
        return FakeResponse(chunks=(b"abc", b"def"))

    with tempfile.TemporaryDirectory() as tmp:
        previous = os.environ.get("METTACLAW_TELEGRAM_ATTACHMENTS_DIR")
        os.environ["METTACLAW_TELEGRAM_ATTACHMENTS_DIR"] = tmp
        try:
            tg.requests.get = fake_get
            tg._token = "fake-token"
            note = tg._download_attachment(message)
        finally:
            if previous is None:
                os.environ.pop("METTACLAW_TELEGRAM_ATTACHMENTS_DIR", None)
            else:
                os.environ["METTACLAW_TELEGRAM_ATTACHMENTS_DIR"] = previous

        saved = pathlib.Path(tmp) / "7-bad_name.pdf"
        assert saved.read_bytes() == b"abcdef"
        assert not list(pathlib.Path(tmp).glob("*.part"))
        assert str(saved) in note
        assert "fake-token" not in note


def test_oversized_attachment_leaves_no_partial_file():
    tg = load_telegram()
    tg._MAX_ATTACHMENT_BYTES = 5
    message = {
        "message_id": 8,
        "document": {"file_id": "file-2", "file_name": "large.bin"},
    }

    def fake_get(url, params=None, timeout=None, stream=False):
        if url.endswith("/getFile"):
            return FakeResponse({"ok": True, "result": {"file_path": "docs/large.bin"}})
        return FakeResponse(chunks=(b"1234", b"56"))

    with tempfile.TemporaryDirectory() as tmp:
        previous = os.environ.get("METTACLAW_TELEGRAM_ATTACHMENTS_DIR")
        os.environ["METTACLAW_TELEGRAM_ATTACHMENTS_DIR"] = tmp
        try:
            tg.requests.get = fake_get
            tg._token = "fake-token"
            note = tg._download_attachment(message)
        finally:
            if previous is None:
                os.environ.pop("METTACLAW_TELEGRAM_ATTACHMENTS_DIR", None)
            else:
                os.environ["METTACLAW_TELEGRAM_ATTACHMENTS_DIR"] = previous

        assert "download failed: ValueError" in note
        assert list(pathlib.Path(tmp).iterdir()) == []


if __name__ == "__main__":
    test_poll_logs_before_advancing_offset_and_queues_allowed_message()
    test_channel_posts_are_logged_with_kind()
    test_log_failure_does_not_block_message_delivery_or_offset()
    test_attachment_download_is_atomic_and_sanitized()
    test_oversized_attachment_leaves_no_partial_file()
