"""A minimal tmux interface for the agent: see the windows, read a pane,
type into the Claude Code window.

Reading is unrestricted (panes on this box are shared workspace). SENDING is
restricted to an allowlist — default only the Claude Code window — because a
misdirected send-keys lands as INPUT in another agent's session; one wrong
target can derail a long-running lane. Sends also require the operator's
claude-code authorization flag: typing into Claude Code's prompt IS invoking
Claude Code.
"""

import os
import subprocess

import claude_bridge


def _run(*args):
    try:
        r = subprocess.run(["tmux", *args], capture_output=True, text=True,
                           timeout=15)
        return r.returncode, (r.stdout or r.stderr).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "%s: %s" % (type(exc).__name__, exc)


def _send_targets():
    raw = os.environ.get("METTACLAW_TMUX_SEND_TARGETS", "CC-mama")
    return [t.strip() for t in raw.split(",") if t.strip()]


def windows():
    code, out = _run("list-windows", "-a",
                     "-F", "#{session_name}:#{window_index} #{window_name}")
    if code != 0:
        return "tmux-windows failed: %s" % out
    return out or "(no tmux windows)"


def peek(window, lines=25):
    try:
        n = max(1, min(200, int(lines)))
    except (TypeError, ValueError):
        n = 25
    code, out = _run("capture-pane", "-p", "-t", str(window))
    if code != 0:
        return ("tmux-peek failed: %s — name a window from (tmux-windows), "
                "e.g. \"oruzi:CC-mama\"" % out)
    tail = [l for l in out.splitlines() if l.strip()][-n:]
    return "\n".join(tail) or "(pane is empty)"


def send(window, text):
    window = str(window)
    wname = window.split(":", 1)[-1]
    allowed = _send_targets()
    if wname not in allowed and window not in allowed:
        return ("tmux-send refused: %r is not an allowed target (%s). "
                "Reading is open; typing into other agents' sessions is not — "
                "a stray send derails their work." % (window, ", ".join(allowed)))
    if not claude_bridge.authorized():
        return ("tmux-send refused: Zar's /claude_code_authorization toggle "
                "is OFF")
    text = str(text).strip()
    if not text:
        return "tmux-send: empty message"
    target = window if ":" in window else "oruzi:" + window
    code, out = _run("send-keys", "-t", target, text)
    if code != 0:
        return "tmux-send failed: %s" % out
    _run("send-keys", "-t", target, "Enter")
    return ("sent to %s — the session will see it as user input; "
            "(tmux-peek \"%s\" 30) in a later turn to read the reply"
            % (target, target))
