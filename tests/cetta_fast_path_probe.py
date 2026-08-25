"""Embedded-CeTTa witness for Telegram's independent read-control lane."""

from __future__ import annotations

import threading
import time

import telegram


def mode_while_evaluator_waits():
    """Return only after ``/mode`` overtakes a blocked serialized control.

    CeTTa calls this function synchronously from its evaluator.  The function
    deliberately occupies that call while Telegram's control threads run, so
    success witnesses the embedded-Python scheduling boundary used by the live
    service rather than merely the ordinary CPython unit-test process.
    """

    slow_entered = threading.Event()
    release_slow = threading.Event()
    mode_seen = threading.Event()
    observed = []
    original = telegram._handle_slash_command

    def fake_handle(_chat, _sender, text):
        observed.append(text)
        if text == "/quota":
            slow_entered.set()
            release_slow.wait(2.0)
        elif text == "/mode":
            mode_seen.set()

    telegram._handle_slash_command = fake_handle
    try:
        telegram._enqueue_slash_command({"id": 1}, {"id": 1}, "/quota")
        if not slow_entered.wait(1.0):
            return "CETTA_FAST_PATH_FAIL: serialized control did not block"
        started = time.monotonic()
        lane = telegram._dispatch_slash_command(
            {"id": 1}, {"id": 1}, "/mode"
        )
        if not mode_seen.wait(0.75):
            return "CETTA_FAST_PATH_FAIL: mode waited behind blocked control"
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if lane != "fast-read":
            return "CETTA_FAST_PATH_FAIL: wrong lane %s" % lane
        return "CETTA_FAST_PATH_OK:%dms" % elapsed_ms
    finally:
        release_slow.set()
        telegram._control_queue.join()
        telegram._handle_slash_command = original
