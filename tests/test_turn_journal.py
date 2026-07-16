from pathlib import Path
import json
import tempfile
import unittest

from services.memory.turn_journal import (
    InvalidTransition,
    TurnJournal,
    make_turn_id,
)


class TurnJournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "telegram-turns-v1.jsonl"
        self.journal = TurnJournal(
            self.path,
            clock=lambda: "2026-07-14T12:00:00+00:00",
        )
        self.update = {
            "update_id": 42,
            "message": {"chat": {"id": 7}, "text": "hello"},
        }

    def tearDown(self):
        self.tmp.cleanup()

    def begin_turn(self, intents=()):
        received = self.journal.record_received("bot-1", 42, self.update)
        self.assertEqual(received.kind, "ReceivedDurable")
        turn_id = received.turn_id
        self.journal.record_offset_committed(turn_id, 43)
        keys = self.journal.record_actions_committed(turn_id, intents)
        return turn_id, keys

    def reopen(self):
        return TurnJournal(
            self.path,
            clock=lambda: "2026-07-14T12:01:00+00:00",
        )

    def test_receipt_precedes_offset_and_is_idempotent(self):
        received = self.journal.record_received("bot-1", 42, self.update)
        self.assertEqual(received.kind, "ReceivedDurable")
        again = self.journal.record_received("bot-1", 42, self.update)
        self.assertEqual(again.kind, "AlreadyReceived")
        self.assertEqual(received.turn_id, make_turn_id("bot-1", 42))
        reopened = self.reopen()
        self.assertIn(received.turn_id, reopened.turns)

    def test_same_turn_id_cannot_change_content(self):
        self.journal.record_received("bot-1", 42, self.update)
        changed = {**self.update, "message": {"text": "different"}}
        with self.assertRaises(InvalidTransition):
            self.journal.record_received("bot-1", 42, changed)

    def test_actions_require_durable_receipt_and_committed_offset(self):
        with self.assertRaises(InvalidTransition):
            self.journal.record_actions_committed("missing", [])
        received = self.journal.record_received("bot-1", 42, self.update)
        with self.assertRaises(InvalidTransition):
            self.journal.record_actions_committed(received.turn_id, [])

    def test_send_key_is_deterministic_on_replay(self):
        intent = {"kind": "telegram", "chat_id": "7", "text": "reply"}
        turn_id, keys = self.begin_turn([intent])
        replayed = self.journal.record_actions_committed(turn_id, [intent])
        self.assertEqual(keys, replayed)

    def test_durable_event_order_matches_commit_protocol(self):
        turn_id, (send_key,) = self.begin_turn(
            [{"kind": "telegram", "chat_id": "7", "text": "reply"}]
        )
        self.journal.prepare_send(send_key)
        self.journal.record_sent(send_key, 99)
        self.journal.mark_turn_done(turn_id)
        event_types = [
            json.loads(line)["event_type"]
            for line in self.path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(
            event_types,
            [
                "Generation",
                "Received",
                "OffsetCommitted",
                "ActionsCommitted",
                "Sending",
                "Sent",
                "TurnDone",
            ],
        )

    def test_crash_before_http_drops_in_doubt_instead_of_resending(self):
        turn_id, (send_key,) = self.begin_turn(
            [{"kind": "telegram", "chat_id": "7", "text": "reply"}]
        )
        self.assertEqual(
            self.journal.prepare_send(send_key).kind, "SendPrepared"
        )
        recovered = self.reopen()
        self.assertEqual(recovered.recover_in_doubt(), (send_key,))
        self.assertEqual(
            recovered.prepare_send(send_key).kind, "AlreadyDropped"
        )
        self.assertEqual(
            recovered.mark_turn_done(turn_id).kind, "TurnDone"
        )

    def test_crash_after_http_success_cannot_duplicate_visible_send(self):
        turn_id, (send_key,) = self.begin_turn(
            [{"kind": "telegram", "chat_id": "7", "text": "reply"}]
        )
        self.journal.prepare_send(send_key)
        # Model HTTP success followed by process death before record_sent.
        recovered = self.reopen()
        recovered.recover_in_doubt()
        self.assertEqual(
            recovered.prepare_send(send_key).kind, "AlreadyDropped"
        )
        self.assertEqual(recovered.snapshot()["sends"], 1)
        recovered.mark_turn_done(turn_id)

    def test_recorded_send_is_not_sent_twice(self):
        turn_id, (send_key,) = self.begin_turn(
            [{"kind": "telegram", "chat_id": "7", "text": "reply"}]
        )
        self.journal.prepare_send(send_key)
        self.journal.record_sent(send_key, 99)
        recovered = self.reopen()
        self.assertEqual(
            recovered.prepare_send(send_key).kind, "AlreadySent"
        )
        self.assertEqual(recovered.mark_turn_done(turn_id).kind, "TurnDone")

    def test_turn_without_sends_can_finish(self):
        turn_id, keys = self.begin_turn([])
        self.assertEqual(keys, ())
        self.assertEqual(
            self.journal.mark_turn_done(turn_id).kind, "TurnDone"
        )

    def test_turn_cannot_finish_with_pending_send(self):
        turn_id, _ = self.begin_turn(
            [{"kind": "telegram", "chat_id": "7", "text": "reply"}]
        )
        with self.assertRaises(InvalidTransition):
            self.journal.mark_turn_done(turn_id)

    def test_snapshot_never_contains_message_content(self):
        self.begin_turn(
            [{"kind": "telegram", "chat_id": "7", "text": "private reply"}]
        )
        self.assertNotIn("private reply", repr(self.journal.snapshot()))


if __name__ == "__main__":
    unittest.main()
