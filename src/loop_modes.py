"""Persistent loop-policy modes shared by the MeTTa loop and operator UI."""

import json
import os
import threading


MODES = {
    "generic": {
        "description": "current event-armed loop; no automatic idle bursts",
        "reasoning": None,
    },
    "coding": {
        "description": "generic timing with high reasoning effort",
        "reasoning": "high",
    },
    "claw23": {
        "description": "50-step fast bursts separated by 60-second input waits",
        "reasoning": None,
    },
}

_lock = threading.RLock()


def _path():
    return os.environ.get("METTACLAW_LOOP_MODE_PATH", "memory/loop_mode.json")


def _load():
    try:
        with open(_path(), "r", encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, dict):
            raise ValueError("mode state is not an object")
    except (OSError, TypeError, ValueError):
        data = {}
    mode = str(data.get("mode", "generic")).strip().lower()
    if mode not in MODES:
        mode = "generic"
    return {
        "mode": mode,
        "autonomy_paused": bool(data.get("autonomy_paused", False)),
    }


def _save(data):
    path = _path()
    parent = os.path.dirname(path)
    try:
        if parent:
            os.makedirs(parent, exist_ok=True)
        temporary = path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
        return True
    except OSError as exc:
        print("[loop-mode] save failed:", exc)
        return False


def current_mode():
    with _lock:
        return _load()["mode"]


def mode_view():
    mode = current_mode()
    return "active mode: %s — %s" % (mode, MODES[mode]["description"])


def modes_view():
    current = current_mode()
    return "\n".join(
        ("● " if name == current else "  ") + name + " — " + spec["description"]
        for name, spec in MODES.items()
    )


def set_mode(name):
    name = str(name or "").strip().lower()
    if name not in MODES:
        return "mode-set failed: choose one of %s" % ", ".join(MODES)
    with _lock:
        data = _load()
        data["mode"] = name
        # Selecting a life rhythm is an explicit request to run it. A later
        # (rest) can still suspend autonomous renewal without changing mode.
        data["autonomy_paused"] = False
        if not _save(data):
            return "mode-set failed: could not persist"
    return "mode set to '%s'; persists across restarts" % name


def reasoning_mode(default):
    override = MODES[current_mode()]["reasoning"]
    return override or str(default)


def wait_seconds(loops_left, requested_seconds):
    """Return the wait before the next cognitive tick.

    Channel polling has its own thread and is deliberately not governed by
    this value. In claw23, an exhausted burst waits 60 seconds for activity;
    explicit longer rests remain longer.
    """
    try:
        loops_left = int(loops_left)
    except (TypeError, ValueError):
        loops_left = 0
    try:
        requested = max(0, int(float(requested_seconds)))
    except (TypeError, ValueError):
        requested = 1
    with _lock:
        state = _load()
    if state["mode"] == "claw23" and loops_left <= 0:
        # A normal completed burst has the exact claw23 cadence. Explicit
        # (rest N) sets autonomy_paused, preserving the agent's chosen N.
        return requested if state["autonomy_paused"] else 60
    return requested


def autonomous_ready(loops_left, wait_result):
    """Whether a completed claw23 input wait should renew cognition."""
    try:
        exhausted = int(loops_left) <= 0
    except (TypeError, ValueError):
        exhausted = True
    with _lock:
        state = _load()
    timed_out = str(wait_result).startswith("rested ")
    return 1 if (state["mode"] == "claw23" and exhausted and timed_out
                 and not state["autonomy_paused"]) else 0


def pause_autonomy():
    """Make explicit rest sovereign over claw23's automatic renewal."""
    with _lock:
        data = _load()
        data["autonomy_paused"] = True
        return 1 if _save(data) else 0


def resume_autonomy():
    """A new human event resumes the selected loop policy."""
    with _lock:
        data = _load()
        if not data["autonomy_paused"]:
            return 1
        data["autonomy_paused"] = False
        return 1 if _save(data) else 0


def autonomy_paused():
    with _lock:
        return 1 if _load()["autonomy_paused"] else 0
