"""Background jobs wake the agent when they end, with their result.

Like the background tasks of coding agents: a job starts at once, keeps no
turn waiting, and its end arrives as a [runtime] activity line that also ends
a rest.  The event never redirects where a plain send goes.
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(ROOT / "src"))
sys.path.insert(0, os.fspath(ROOT / "channels"))

import helper  # noqa: E402
import jobs  # noqa: E402
import telegram  # noqa: E402


def _reset_queue():
    with telegram._msg_lock:
        del telegram._pending_messages[:]
        del telegram._prepared_messages[:]
        telegram._activity_epoch = 0
        telegram._reply_chat_id = ""
        telegram._last_message_is_human = False
        telegram._last_from_bot = False
        telegram._last_arm_tier = "full"
    telegram._wake_event.clear()
    telegram._wake_reason = ""


class BackgroundJobTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(
            os.environ, {"METTACLAW_JOBS_DIR": self.tmp.name})
        self.env.start()
        self.events = []
        self.capture = mock.patch.object(
            telegram, "enqueue_runtime_event",
            lambda text, reason="": self.events.append((text, reason)))
        self.capture.start()

    def tearDown(self):
        self.capture.stop()
        self.env.stop()
        self.tmp.cleanup()

    def wait_for_event(self, seconds=15):
        deadline = time.time() + seconds
        while not self.events and time.time() < deadline:
            time.sleep(0.1)
        self.assertTrue(self.events, "no completion event arrived")
        return self.events[-1]

    def test_finished_job_reports_exit_duration_and_output(self):
        reply = jobs.start("echo made-it; exit 3")
        self.assertTrue(reply.startswith("job 1 started"), reply)
        text, reason = self.wait_for_event()
        self.assertIn("job 1 finished with exit 3", text)
        self.assertIn("made-it", text)
        self.assertEqual(reason, "job 1 finished")
        self.assertIn("job 1 done exit 3", jobs.status())
        self.assertIn("made-it", jobs.output("1"))

    def test_stopped_job_says_so(self):
        jobs.start("sleep 30")
        self.assertIn("stopping", jobs.stop("1"))
        text, _ = self.wait_for_event()
        self.assertIn("job 1 was stopped", text)

    def test_jobs_lost_to_a_restart_are_reported_honestly(self):
        jobs._save({"id": "7", "command": "sleep 99", "pid": 999999999,
                    "started": time.time() - 60, "log": "/dev/null",
                    "state": "running"})
        self.assertIn("ended while the runtime was down", jobs.status())

    def test_empty_command_starts_nothing(self):
        self.assertIn("nothing started", jobs.start("   "))


class RuntimeEventRoutingTest(unittest.TestCase):
    def setUp(self):
        _reset_queue()

    def tearDown(self):
        _reset_queue()

    def test_runtime_event_wakes_and_keeps_the_reply_target(self):
        telegram._reply_chat_id = "181"
        telegram.enqueue_runtime_event("job 2 finished with exit 0", "job 2")
        self.assertTrue(telegram._wake_event.is_set())
        batch = telegram.getActivityBatch()
        self.assertIn("[runtime] job 2 finished", batch)
        self.assertEqual(telegram._reply_chat_id, "181")
        self.assertEqual(telegram.lastMessageIsHuman(), 1)
        self.assertEqual(telegram._last_arm_tier, "light")

    def test_a_message_beside_the_event_still_decides_the_reply(self):
        telegram.enqueue_runtime_event("job 3 finished", "job 3")
        telegram._set_last("555", "hello", from_bot=False, arm_tier="full")
        telegram.getActivityBatch()
        self.assertEqual(telegram._reply_chat_id, "555")
        self.assertEqual(telegram._last_arm_tier, "full")


class VitalsTest(unittest.TestCase):
    def test_vitals_reports_the_machine(self):
        text = helper.vitals()
        if os.path.exists("/proc/meminfo"):
            self.assertIn("memory ", text)
            self.assertIn("load ", text)


if __name__ == "__main__":
    unittest.main()
