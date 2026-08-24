import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import effect_receipts  # noqa: E402


class EffectReceiptTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = pathlib.Path(self.temporary.name) / "receipts.jsonl"
        self.environment = mock.patch.dict(os.environ, {
            "METTACLAW_EFFECT_RECEIPT_PATH": str(self.path),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_returned_is_not_rendered_as_success(self):
        effect_receipts.record_command(
            4, "returned", ["send-file", "report.md"],
            "partial(send-file failed: no chat)",
        )
        rendered = effect_receipts.view()
        self.assertIn("returned means only", rendered)
        self.assertIn("partial(send-file failed", rendered)
        self.assertNotIn("disposition=success", rendered)

    def test_withheld_suffix_is_explicitly_nonexecuted(self):
        effect_receipts.record_suffix(
            9, "withheld", [["tmux-peek", "oruzi:7"], ["pin", "done"]],
            "new_stimulus",
        )
        rendered = effect_receipts.view()
        self.assertIn("withheld/deferred commands did not run", rendered)
        self.assertIn("disposition=withheld", rendered)
        self.assertIn("new_stimulus", rendered)

    def test_records_are_append_only_json_lines(self):
        effect_receipts.record_command(1, "returned", ["help", "send"], "ok")
        effect_receipts.record_suffix(1, "deferred", [["help", "query"]],
                                      "batch_limit")
        entries = [json.loads(line) for line in
                   self.path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([entry["disposition"] for entry in entries],
                         ["returned", "deferred"])

    def test_no_configured_path_is_a_noop(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                effect_receipts.record_command(1, "returned", "x", "y"), 0
            )
            self.assertEqual(effect_receipts.view(), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
