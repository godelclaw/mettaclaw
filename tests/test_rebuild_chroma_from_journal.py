"""Journal validation for the offline Chroma rebuild utility."""

import json
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import rebuild_chroma_from_journal as rebuild  # noqa: E402


class JournalLoadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)

    def write(self, name, rows):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")

    def record(self, item_id="one", content="memory", timestamp="2026-01-01"):
        return {"id": item_id, "content": content, "time": timestamp,
                "collection": "memories"}

    def test_exact_duplicate_is_deduplicated(self):
        row = self.record()
        self.write("2026/01/01.jsonl", [row])
        self.write("legacy.jsonl", [dict(row, embedding=[0.0])])
        records, audit = rebuild.load_records(self.root, "memories")
        self.assertEqual(len(records), 1)
        self.assertEqual(audit["source_rows"], 2)
        self.assertEqual(audit["duplicate_rows"], 1)

    def test_conflicting_duplicate_is_rejected(self):
        self.write("a.jsonl", [self.record()])
        self.write("b.jsonl", [self.record(content="different")])
        with self.assertRaisesRegex(ValueError, "conflicting"):
            rebuild.load_records(self.root, "memories")

    def test_invalid_and_other_collection_rows(self):
        self.write("a.jsonl", [
            dict(self.record(), collection="other"),
            self.record(item_id="two"),
        ])
        records, audit = rebuild.load_records(self.root, "memories")
        self.assertEqual([row["id"] for row in records], ["two"])
        self.assertEqual(audit["ignored_other_collection_rows"], 1)


if __name__ == "__main__":
    unittest.main()
