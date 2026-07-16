import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import uuid

from services.memory.journal import (
    JournalConfigurationMismatch,
    JournalCorruption,
    MemoryJournal,
    PRIVACY_CLASS,
    SCHEMA,
    ZERO_HASH,
    embedding_fingerprint,
    verify_journal,
)
from services.memory.verify_journal import main as verify_main


METADATA = {
    "backend": "fixture",
    "dim": 3,
    "normalized": True,
    "protocol": "fixture-v1",
}


class SequenceUuid:
    def __init__(self):
        self.value = 0

    def __call__(self):
        self.value += 1
        return uuid.UUID(int=self.value)


class MemoryJournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "events-v1.jsonl"
        self.uuids = SequenceUuid()
        self.journal = MemoryJournal(
            self.path,
            METADATA,
            clock=lambda: "2026-07-14T12:00:00+00:00",
            uuid_factory=self.uuids,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def rows(self):
        return [
            json.loads(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
        ]

    def test_generation_is_self_describing_and_private(self):
        generation = self.rows()[0]
        self.assertEqual(generation["schema"], SCHEMA)
        self.assertEqual(generation["sequence"], 0)
        self.assertEqual(generation["prev_event_hash"], ZERO_HASH)
        self.assertEqual(generation["embedding"], METADATA)
        self.assertEqual(
            generation["embedding_fingerprint"],
            embedding_fingerprint(METADATA),
        )
        self.assertEqual(generation["privacy_class"], PRIVACY_CLASS)
        self.assertFalse(generation["index_is_rebuildable"])

    def test_remember_event_is_hash_chained(self):
        event = self.journal.append_remember(
            "hello",
            memory_id="memory-1",
            timestamp="2026-07-14 12:01:00",
        )
        generation, remember = self.rows()
        self.assertEqual(event, remember)
        self.assertEqual(remember["memory_id"], "memory-1")
        self.assertEqual(
            remember["prev_event_hash"], generation["event_hash"]
        )
        result = self.journal.verify()
        self.assertTrue(result.valid)
        self.assertEqual(result.event_count, 2)
        self.assertEqual(result.last_hash, remember["event_hash"])

    def test_content_tampering_is_detected_without_echoing_content(self):
        self.journal.append_remember("private text", memory_id="memory-1")
        rows = self.rows()
        rows[1]["content"] = "changed"
        self.path.write_text(
            "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
            encoding="utf-8",
        )
        result = verify_journal(self.path)
        self.assertFalse(result.valid)
        self.assertEqual(result.error, "event hash mismatch")
        self.assertNotIn("private text", json.dumps(result.as_dict()))
        self.assertNotIn("changed", json.dumps(result.as_dict()))

    def test_truncated_tail_is_detected(self):
        self.journal.append_remember("hello", memory_id="memory-1")
        with self.path.open("ab") as handle:
            handle.write(b'{"event_type":"Remember"')
        result = verify_journal(self.path)
        self.assertFalse(result.valid)
        self.assertEqual(result.error, "truncated final line")

    def test_reopen_refuses_tampered_journal(self):
        self.journal.append_remember("hello", memory_id="memory-1")
        with self.path.open("ab") as handle:
            handle.write(b"not-json\n")
        with self.assertRaises(JournalCorruption):
            MemoryJournal(self.path, METADATA)

    def test_reopen_refuses_embedding_drift(self):
        with self.assertRaises(JournalConfigurationMismatch):
            MemoryJournal(self.path, {**METADATA, "dim": 4})

    def test_reopen_continues_sequence_and_chain(self):
        first = self.journal.append_remember("one", memory_id="memory-1")
        reopened = MemoryJournal(
            self.path,
            METADATA,
            clock=lambda: "2026-07-14T12:02:00+00:00",
            uuid_factory=self.uuids,
        )
        second = reopened.append_remember("two", memory_id="memory-2")
        self.assertEqual(second["sequence"], 2)
        self.assertEqual(second["prev_event_hash"], first["event_hash"])
        self.assertTrue(reopened.verify().valid)

    def test_verify_only_cli_reports_metadata_not_content(self):
        self.journal.append_remember("private text", memory_id="memory-1")
        with mock.patch("builtins.print") as output:
            self.assertEqual(verify_main([str(self.path)]), 0)
        rendered = output.call_args.args[0]
        self.assertIn('"valid": true', rendered)
        self.assertNotIn("private text", rendered)


if __name__ == "__main__":
    unittest.main()
