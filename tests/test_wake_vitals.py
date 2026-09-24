"""Runtime-measured metadata the model sees but does not have to infer.

Each message carries Telegram's own send time, so a delivery delay is
visible; each turn carries the time since the previous turn and the
machine's load and memory, so a starved machine is not mistaken for idling.
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
import telegram  # noqa: E402


class WakeVitalsTest(unittest.TestCase):
    def setUp(self):
        helper._WAKE.update(iteration=None, at=None, view="")
        self.tmp = tempfile.TemporaryDirectory()
        self.history = Path(self.tmp.name) / "history.metta"

    def tearDown(self):
        helper._WAKE.update(iteration=None, at=None, view="")
        self.tmp.cleanup()

    def wake(self, iteration, now):
        with mock.patch.dict(os.environ, {
                 "METTACLAW_HISTORY_PATH": os.fspath(self.history)}), \
             mock.patch.object(helper, "_machine_view",
                               return_value=["load 309/16", "mem 94%"]), \
             mock.patch.object(helper.time, "time", return_value=now):
            return helper.wake_view(iteration)

    def test_first_wake_measures_from_the_last_turn_in_history(self):
        last = time.mktime(time.strptime("2026-09-24 16:05:00",
                                         "%Y-%m-%d %H:%M:%S"))
        self.history.write_text(
            '("2026-09-24 16:04:10" ((pin "a")))\n'
            '("2026-09-24 16:05:00" ((shell "b")))\n', encoding="utf-8")
        self.assertEqual(self.wake(75, last + 2475),
                         "+41m15s since last turn | load 309/16 | mem 94%")

    def test_one_view_per_turn_then_the_gap_to_the_next(self):
        first = self.wake(7, 1000.0)
        self.assertEqual(first, "load 309/16 | mem 94%")
        self.assertEqual(self.wake(7, 1030.0), first)
        self.assertEqual(self.wake(8, 1042.0),
                         "+42s since last turn | load 309/16 | mem 94%")

    def test_long_gaps_read_in_hours(self):
        self.wake(1, 0.0)
        self.assertTrue(self.wake(2, 7500.0).startswith(
            "+2h05m since last turn"))

    def test_machine_view_reads_proc(self):
        parts = helper._machine_view()
        if os.path.exists("/proc/loadavg"):
            self.assertTrue(parts[0].startswith("load "))
            self.assertTrue(parts[-1].startswith("mem "))

    def test_message_header_carries_its_send_time(self):
        sent = 1790000000
        header = telegram._format_message(
            {"update_id": 5}, "message",
            {"message_id": 9, "date": sent,
             "chat": {"id": 1, "type": "private"},
             "from": {"id": 2, "is_bot": False, "username": "z"}},
            "hi")
        expected = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(sent))
        self.assertIn('sent_at="%s"' % expected, header)
        self.assertNotIn("edited_at", header)


if __name__ == "__main__":
    unittest.main()
