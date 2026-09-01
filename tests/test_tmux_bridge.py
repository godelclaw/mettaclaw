#!/usr/bin/env python3
import pathlib
import sys
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import tmux_bridge


def test_send_accepts_any_window_on_the_user_tmux_server():
    calls = []

    def fake_run(*args):
        calls.append(args)
        return 0, ""

    with mock.patch.object(tmux_bridge, "_run", side_effect=fake_run), \
            mock.patch.object(tmux_bridge.time, "sleep") as pause:
        result = tmux_bridge.send("agent:5", "hello")

    assert result.startswith("sent to agent:5")
    assert calls == [
        ("send-keys", "-l", "-t", "agent:5", "--", "hello"),
        ("send-keys", "-t", "agent:5", "Enter"),
    ]
    pause.assert_called_once_with(2.0)


def test_send_keeps_a_bare_window_target_bare():
    with mock.patch.object(tmux_bridge, "_run", return_value=(0, "")) as run, \
            mock.patch.object(tmux_bridge.time, "sleep"):
        result = tmux_bridge.send("godel", "hello")

    assert result.startswith("sent to godel")
    run.assert_any_call("send-keys", "-l", "-t", "godel", "--", "hello")


def test_send_rejects_empty_input_without_touching_tmux():
    with mock.patch.object(tmux_bridge, "_run") as run:
        assert tmux_bridge.send("agent:5", "   ") == "tmux-send: empty message"
    run.assert_not_called()


def test_send_reports_tmux_target_failure():
    with mock.patch.object(
            tmux_bridge, "_run", return_value=(1, "can't find window")):
        assert tmux_bridge.send("agent:missing", "hello") == (
            "tmux-send failed: can't find window")


def test_send_reports_submit_failure_after_the_pause():
    with mock.patch.object(
            tmux_bridge, "_run",
            side_effect=[(0, ""), (1, "can't submit")]), \
            mock.patch.object(tmux_bridge.time, "sleep") as pause:
        assert tmux_bridge.send("agent:5", "hello") == (
            "tmux-send submit failed: can't submit")
    pause.assert_called_once_with(2.0)
