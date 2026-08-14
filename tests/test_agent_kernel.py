import importlib
import json
import os
import pathlib
import sys
import tempfile
import threading
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import agent_kernel  # noqa: E402
import helper  # noqa: E402


class AgentKernelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = pathlib.Path(self.tmp.name) / "events.jsonl"
        os.environ["METTACLAW_EVENT_LOG_PATH"] = str(self.log)
        agent_kernel._CACHE.clear()

    def tearDown(self):
        os.environ.pop("METTACLAW_EVENT_LOG_PATH", None)
        agent_kernel._CACHE.clear()
        self.tmp.cleanup()

    def issue(self, conversation, context, controller, proposal):
        invocation = agent_kernel.begin_invocation(
            conversation, context, controller)
        return agent_kernel.issue_decision(invocation, proposal)

    def test_canonical_digest_ignores_mapping_insertion_order(self):
        self.assertEqual(
            agent_kernel.digest({"a": 1, "b": 2}),
            agent_kernel.digest({"b": 2, "a": 1}),
        )

    def test_stable_source_identity_turns_replay_into_stutter(self):
        first = agent_kernel.record_input(
            "telegram:update:7", "telegram:42:root", "hello")
        replay = agent_kernel.record_input(
            "telegram:update:7", "telegram:42:root", "hello")
        self.assertEqual(first["status"], "appended")
        self.assertEqual(replay, {"status": "duplicate", "id": first["id"]})
        self.assertEqual(len(agent_kernel.read_events()), 1)

    def test_same_identity_with_different_bytes_is_an_integrity_error(self):
        agent_kernel.record_input("source:7", "chat", "first")
        with self.assertRaises(agent_kernel.EventLogError):
            agent_kernel.record_input("source:7", "chat", "changed")

    def test_replay_reconstructs_frontier_effects_and_working_capsule(self):
        inbound = agent_kernel.record_input(
            "telegram:update:8", "telegram:42:root", "question")
        agent_kernel.record_effect(
            "reply:8", "telegram:42:root", "answer", {"message_id": 9})
        state = {
            "loops": 4,
            "sleepInterval": 1,
            "lastresults": "verified",
            "last_heartbeat": 12.5,
            "saved_at": 13.0,
        }
        agent_kernel.record_working_set(state)
        projection = agent_kernel.project()
        self.assertEqual(projection["count"], 3)
        self.assertEqual(
            projection["frontier"]["telegram:42:root"], inbound["id"])
        self.assertEqual(projection["effects"], {"reply:8"})
        self.assertEqual(projection["working_set"], state)

    def test_receipt_binds_current_frontier_context_controller_and_proposal(self):
        inbound = agent_kernel.record_input("source:9", "chat:a", "hello")
        receipt_id = self.issue(
            "chat:a", "exact context", "controller-r1", "(send answer)")
        receipt = agent_kernel.project()["receipts"][receipt_id]
        self.assertEqual(receipt["frontiers"], {"chat:a": inbound["id"]})
        self.assertEqual(receipt["context_digest"],
                         agent_kernel.digest("exact context"))
        self.assertEqual(receipt["proposal_digest"],
                         agent_kernel.digest("(send answer)"))
        self.assertEqual(agent_kernel.receipt_current(
            receipt_id, "controller-r1"), 1)
        self.assertEqual(agent_kernel.receipt_current(
            receipt_id, "controller-r2"), 0)

    def test_new_same_conversation_input_invalidates_receipt(self):
        agent_kernel.record_input("source:10", "chat:a", "first")
        receipt_id = self.issue(
            "chat:a", "context", "controller", "proposal")
        agent_kernel.record_input("source:11", "chat:a", "newer")
        self.assertEqual(agent_kernel.receipt_current(
            receipt_id, "controller"), 0)

    def test_other_conversation_does_not_invalidate_receipt(self):
        agent_kernel.record_input("source:12", "chat:a", "first")
        receipt_id = self.issue(
            "chat:a", "context", "controller", "proposal")
        agent_kernel.record_input("source:13", "chat:b", "unrelated")
        self.assertEqual(agent_kernel.receipt_current(
            receipt_id, "controller"), 1)

    def test_semantic_effect_attempt_is_durable_and_proposal_independent(self):
        agent_kernel.record_input("source:14", "chat:a", "request")
        first_receipt = self.issue(
            "chat:a", "context one", "controller", "proposal one")
        first = agent_kernel.prepare_effect(
            first_receipt, "controller", "telegram.send", "target", "hello")
        self.assertEqual(first["status"], "appended")
        replay = agent_kernel.prepare_effect(
            first_receipt, "controller", "telegram.send", "target", "hello")
        self.assertEqual(replay["status"], "duplicate")

        second_receipt = self.issue(
            "chat:a", "context two", "controller", "different proposal")
        semantic_replay = agent_kernel.prepare_effect(
            second_receipt, "controller", "telegram.send", "target", "hello")
        self.assertEqual(semantic_replay["status"], "duplicate")
        self.assertEqual(semantic_replay["effect_key"], first["effect_key"])

        observed = agent_kernel.observe_effect(
            first["effect_key"], "delivered", {"message_id": 7})
        self.assertEqual(observed["status"], "appended")
        projection = agent_kernel.project()
        self.assertIn(first["effect_key"], projection["effect_attempts"])
        self.assertEqual(
            projection["effect_observations"][first["effect_key"]]["status"],
            "delivered")

    def test_stale_receipt_cannot_prepare_effect(self):
        agent_kernel.record_input("source:15", "chat:a", "request")
        receipt_id = self.issue(
            "chat:a", "context", "controller", "proposal")
        agent_kernel.record_input("source:16", "chat:a", "new request")
        self.assertEqual(
            agent_kernel.prepare_effect(
                receipt_id, "controller", "telegram.send", "target", "hello"),
            {"status": "stale"},
        )

    def test_new_input_during_invocation_cannot_relabel_stale_answer(self):
        first = agent_kernel.record_input("source:17", "chat:a", "first")
        invocation = agent_kernel.begin_invocation(
            "chat:a", "context containing first", "controller")
        agent_kernel.record_input("source:18", "chat:a", "newer")
        receipt_id = agent_kernel.issue_decision(invocation, "answer to first")
        receipt = agent_kernel.project()["receipts"][receipt_id]
        self.assertEqual(receipt["frontiers"], {"chat:a": first["id"]})
        self.assertEqual(
            receipt["context_digest"],
            agent_kernel.digest("context containing first"),
        )
        self.assertEqual(agent_kernel.receipt_current(
            receipt_id, "controller"), 0)

    def test_decision_requires_an_issued_invocation(self):
        with self.assertRaises(agent_kernel.EventLogError):
            agent_kernel.issue_decision("missing-invocation", "proposal")

    def test_consumed_frontier_vector_never_adopts_later_live_frontier(self):
        seen_a = agent_kernel.record_input("source:19", "chat:a", "seen a")
        seen_b = agent_kernel.record_input("source:20", "chat:b", "seen b")
        consumed = {"chat:b": seen_b["id"], "chat:a": seen_a["id"]}
        newer = agent_kernel.record_input("source:21", "chat:a", "unseen")
        invocation = agent_kernel.begin_invocation(
            "chat:a", "context before unseen", "controller",
            json.dumps(consumed),
        )
        receipt_id = agent_kernel.issue_decision(invocation, "old answer")
        receipt = agent_kernel.project()["receipts"][receipt_id]
        self.assertEqual(
            list(receipt["frontiers"]), ["chat:a", "chat:b"])
        self.assertEqual(receipt["frontiers"]["chat:a"], seen_a["id"])
        self.assertNotEqual(receipt["frontiers"]["chat:a"], newer["id"])
        self.assertEqual(agent_kernel.receipt_current(
            receipt_id, "controller"), 0)

    def test_every_consumed_conversation_must_remain_current(self):
        seen_a = agent_kernel.record_input("source:22", "chat:a", "seen a")
        seen_b = agent_kernel.record_input("source:23", "chat:b", "seen b")
        invocation = agent_kernel.begin_invocation(
            "chat:a", "combined context", "controller",
            {"chat:a": seen_a["id"], "chat:b": seen_b["id"]},
        )
        receipt_id = agent_kernel.issue_decision(invocation, "answer")
        self.assertEqual(agent_kernel.receipt_current(
            receipt_id, "controller"), 1)
        agent_kernel.record_input("source:24", "chat:b", "new b")
        self.assertEqual(agent_kernel.receipt_current(
            receipt_id, "controller"), 0)

    def test_truncated_tail_is_discarded_before_next_append(self):
        first = agent_kernel.record_input("source:1", "chat", "one")
        with self.log.open("ab") as stream:
            stream.write(b'{"partial":')
        second = agent_kernel.record_input("source:2", "chat", "two")
        events = agent_kernel.read_events()
        self.assertEqual([event["id"] for event in events],
                         [first["id"], second["id"]])
        self.assertEqual([event["index"] for event in events], [1, 2])

    def test_malformed_complete_event_fails_loudly(self):
        self.log.write_text("not-json\n", encoding="utf-8")
        with self.assertRaises(agent_kernel.EventLogError):
            agent_kernel.read_events()

    def test_threaded_appends_have_one_contiguous_order(self):
        threads = [
            threading.Thread(
                target=agent_kernel.record_input,
                args=("source:%d" % index, "chat", "value:%d" % index),
            )
            for index in range(12)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        events = agent_kernel.read_events()
        self.assertEqual(len(events), 12)
        self.assertEqual([event["index"] for event in events],
                         list(range(1, 13)))

    def test_attention_is_a_deterministic_projection_of_turn_events(self):
        seen = agent_kernel.record_input("source:30", "chat:a", "hello")
        self.assertEqual(agent_kernel.begin_turn(
            7, "operator-event", True, {"chat:a": seen["id"]}), 1)
        begun = agent_kernel.attention_view_text()
        self.assertIn('(node (event "7") event "operator-event")', begun)
        self.assertIn("(node prior-receipt receipt)", begun)
        self.assertIn("(frontier-fresh True)", begun)
        receipt_id = self.issue(
            "chat:a", "context", "controller", "proposal")
        self.assertEqual(agent_kernel.complete_turn(
            7, "commands-parsed", receipt_id), 1)
        completed = agent_kernel.attention_view_text()
        self.assertIn(agent_kernel.digest("proposal"), completed)
        self.assertIn(receipt_id, completed)
        self.assertIn('"commands-parsed"', completed)

    def test_attention_freshness_is_derived_not_stored(self):
        seen = agent_kernel.record_input("source:31", "chat:a", "first")
        agent_kernel.begin_turn(
            8, "operator-event", False, {"chat:a": seen["id"]})
        self.assertIn("(pending-input False)",
                      agent_kernel.attention_view_text())
        agent_kernel.record_input("source:32", "chat:a", "newer")
        self.assertIn("(frontier-fresh False)",
                      agent_kernel.attention_view_text())
        self.assertIn("(pending-input True)",
                      agent_kernel.attention_view_text())


class WorkingCapsuleReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["METTACLAW_EVENT_LOG_PATH"] = str(
            pathlib.Path(self.tmp.name) / "events.jsonl")
        os.environ["METTACLAW_WORKING_SET_PATH"] = str(
            pathlib.Path(self.tmp.name) / "working_set.json")
        importlib.reload(agent_kernel)
        importlib.reload(helper)

    def tearDown(self):
        os.environ.pop("METTACLAW_EVENT_LOG_PATH", None)
        os.environ.pop("METTACLAW_WORKING_SET_PATH", None)
        self.tmp.cleanup()

    def test_missing_capsule_reconstructs_from_event_log(self):
        self.assertEqual(helper.working_set_save(7, 3, "receipt", 21.5), 1)
        os.unlink(os.environ["METTACLAW_WORKING_SET_PATH"])
        self.assertEqual(helper.working_boot(), 1)
        self.assertEqual(helper.boot_int("loops", 50), 7)
        self.assertEqual(helper.boot_int("sleepInterval", 1), 3)
        self.assertIn("receipt", helper.boot_str("lastresults", ""))

    def test_snapshot_stays_last_known_good_if_ledger_is_corrupt(self):
        self.assertEqual(helper.working_set_save(6, 2, "safe", 18.0), 1)
        with open(os.environ["METTACLAW_EVENT_LOG_PATH"], "ab") as stream:
            stream.write(b"malformed-complete-line\n")
        self.assertEqual(helper.working_boot(), 1)
        self.assertEqual(helper.boot_int("loops", 50), 6)
        self.assertIn("safe", helper.boot_str("lastresults", ""))

    def test_ledger_failure_does_not_block_snapshot_write(self):
        with mock.patch.object(
                agent_kernel, "record_working_set",
                side_effect=agent_kernel.EventLogError("broken")):
            self.assertEqual(helper.working_set_save(8, 4, "alive", 19.0), 1)
        with open(os.environ["METTACLAW_WORKING_SET_PATH"],
                  encoding="utf-8") as stream:
            snapshot = json.load(stream)
        self.assertEqual(snapshot["loops"], 8)
        self.assertEqual(snapshot["lastresults"], "alive")

    def test_newer_ledger_capsule_supersedes_stale_snapshot(self):
        self.assertEqual(helper.working_set_save(9, 5, "newer", 22.0), 1)
        with open(os.environ["METTACLAW_WORKING_SET_PATH"], "w",
                  encoding="utf-8") as stream:
            json.dump({
                "loops": 1,
                "sleepInterval": 1,
                "lastresults": "stale",
                "last_heartbeat": 1.0,
                "saved_at": 0.0,
            }, stream)
        self.assertEqual(helper.working_boot(), 1)
        self.assertEqual(helper.boot_int("loops", 50), 9)
        self.assertIn("newer", helper.boot_str("lastresults", ""))


if __name__ == "__main__":
    unittest.main()
