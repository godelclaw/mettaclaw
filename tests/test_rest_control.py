"""Rest remains agent-directed while Telegram can report and interrupt it."""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(ROOT / "channels"))

import telegram  # noqa: E402


class RestControlTest(unittest.TestCase):
    def tearDown(self):
        telegram._sleep_until = 0.0
        telegram._wake_event.clear()

    def test_wake_event_is_cleared_before_rest_is_published(self):
        observations = []

        class ProbeEvent:
            def clear(self):
                observations.append(telegram.rest_status()[0])

            def wait(self, timeout):
                return True

        original = telegram._wake_event
        telegram._wake_event = ProbeEvent()
        try:
            self.assertEqual(telegram.sleep_until_message(30),
                             "woken by /wake")
        finally:
            telegram._wake_event = original

        self.assertGreaterEqual(len(observations), 1)
        self.assertFalse(
            observations[0],
            "publishing rest before clearing a stale event can lose /wake")

    def test_agent_requested_rest_has_no_hidden_upper_clamp(self):
        source = (ROOT / "src" / "skills.metta").read_text(encoding="utf-8")
        start = source.index("(= (rest $seconds)")
        end = source.index("\n\n", start)
        rest_rule = source[start:end]
        self.assertNotIn("(min 1800", rest_rule)

    def test_positive_fractional_remainder_is_reported_as_one_second(self):
        telegram._sleep_until = 100.1
        with mock.patch.object(telegram.time, "time", return_value=100.0):
            self.assertEqual(telegram.rest_status(), (True, 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
