import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from src import helper
from src.helper import recycle_requested


class RecycleRequestTests(unittest.TestCase):
    def test_disabled_without_a_configured_path(self):
        with mock.patch.dict(
            os.environ, {"METTACLAW_RECYCLE_REQUEST_PATH": ""}, clear=False
        ):
            result = recycle_requested()
            self.assertIs(type(result), int)
            self.assertEqual(result, 0)

    def test_flag_is_observed_without_consuming_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            flag = Path(tmp) / "recycle.requested"
            flag.write_text("request\n", encoding="utf-8")
            with mock.patch.dict(
                os.environ,
                {"METTACLAW_RECYCLE_REQUEST_PATH": str(flag)},
                clear=False,
            ):
                result = recycle_requested()
                self.assertIs(type(result), int)
                self.assertEqual(result, 1)
                self.assertTrue(flag.exists())

    def test_directory_at_flag_path_is_not_a_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                os.environ,
                {"METTACLAW_RECYCLE_REQUEST_PATH": tmp},
                clear=False,
            ):
                result = recycle_requested()
            self.assertIs(type(result), int)
            self.assertEqual(result, 0)

    def test_safe_receipt_requires_a_live_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = Path(tmp) / "recycle.requested"
            safe = Path(tmp) / "recycle.safe"
            with mock.patch.dict(
                os.environ,
                {"METTACLAW_RECYCLE_REQUEST_PATH": str(request),
                 "METTACLAW_RECYCLE_SAFE_PATH": str(safe)},
                clear=False,
            ):
                self.assertEqual(helper._recycle_mark_safe(), 0)
                self.assertFalse(safe.exists())
                request.write_text("request\n", encoding="utf-8")
                self.assertEqual(helper._recycle_mark_safe(), 1)
                self.assertIn("safely_wrapped_up=", safe.read_text())
                self.assertEqual(safe.stat().st_mode & 0o777, 0o600)

    def test_ack_consumes_request_and_safe_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = Path(tmp) / "recycle.requested"
            safe = Path(tmp) / "recycle.safe"
            events = Path(tmp) / "events.jsonl"
            request.write_text("request\n", encoding="utf-8")
            request_digest = helper._file_sha256(request)
            safe.write_text(
                "request_sha256=%s\nsafe\n" % request_digest,
                encoding="utf-8")
            with mock.patch.dict(
                os.environ,
                {"METTACLAW_RECYCLE_REQUEST_PATH": str(request),
                 "METTACLAW_RECYCLE_SAFE_PATH": str(safe),
                 "METTACLAW_EVENT_LOG_PATH": str(events)},
                clear=False,
            ):
                self.assertEqual(helper.recycle_ack(), 1)
            self.assertFalse(request.exists())
            self.assertFalse(safe.exists())
            payload = json.loads(events.read_text().splitlines()[-1])["payload"]
            self.assertTrue(payload["matched"])
            self.assertEqual(payload["request_digest"], request_digest)

    def test_ack_breaks_stale_pair_and_records_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = Path(tmp) / "recycle.requested"
            safe = Path(tmp) / "recycle.safe"
            events = Path(tmp) / "events.jsonl"
            request.write_text("new request\n", encoding="utf-8")
            safe.write_text("request_sha256=%s\n" % ("0" * 64),
                            encoding="utf-8")
            with mock.patch.dict(
                os.environ,
                {"METTACLAW_RECYCLE_REQUEST_PATH": str(request),
                 "METTACLAW_RECYCLE_SAFE_PATH": str(safe),
                 "METTACLAW_EVENT_LOG_PATH": str(events)},
                clear=False,
            ):
                self.assertEqual(helper.recycle_ack(), 1)
            self.assertFalse(request.exists())
            self.assertFalse(safe.exists())
            payload = json.loads(events.read_text().splitlines()[-1])["payload"]
            self.assertFalse(payload["matched"])

    def test_exit_receipt_requires_successful_persistence(self):
        with mock.patch.object(helper, "_recycle_mark_safe") as mark, \
             mock.patch.object(helper.os, "_exit") as exit_now:
            helper.recycle_exit(0)
            mark.assert_not_called()
            exit_now.assert_called_once_with(0)
        with mock.patch.object(helper, "_recycle_mark_safe") as mark, \
             mock.patch.object(helper.os, "_exit") as exit_now:
            helper.recycle_exit(1)
            mark.assert_called_once_with()
            exit_now.assert_called_once_with(0)


if __name__ == "__main__":
    unittest.main()
