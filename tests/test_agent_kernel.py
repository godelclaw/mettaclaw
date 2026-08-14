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
