"""Persistent loop-policy modes shared by the MeTTa loop and operator UI."""

import json
import os
import threading


MODES = {
    "agent": {
        "description": "event-armed life with bounded bursts",
    },
    "iter": {
        "description": "transformational renewal after each idle boundary",
    },
    "coding": {
        "description": "event-armed task episodes with high reasoning effort",
    },
    "iter-coding": {
        "description": "transformational renewal with high reasoning effort",
    },
}

# Persisted historical selections retain their behavior while the operator UI
# exposes only policy names used by the open MeTTa assemblage.
ALIASES = {
    "default": "agent",
    "generic": "agent",
    "claw23": "iter",
}

_lock = threading.RLock()


def _path():
    return os.environ.get("METTACLAW_LOOP_MODE_PATH", "memory/loop_mode.json")


def _canonical(name):
    name = str(name or "").strip().lower()
    return ALIASES.get(name, name)


def _load():
    try:
        with open(_path(), "r", encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, dict):
            raise ValueError("mode state is not an object")
    except (OSError, TypeError, ValueError):
        data = {}
    mode = _canonical(data.get("mode", "agent"))
    if mode not in MODES:
        mode = "agent"
    return {"mode": mode}


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
    requested = str(name or "").strip().lower()
    name = _canonical(requested)
    if name not in MODES:
        choices = list(MODES) + list(ALIASES)
        return "mode-set failed: choose one of %s" % ", ".join(choices)
    with _lock:
        data = _load()
        data["mode"] = name
        if not _save(data):
            return "mode-set failed: could not persist"
    alias = " (from alias '%s')" % requested if requested != name else ""
    return "mode set to '%s'%s; persists across restarts" % (name, alias)


def wait_timed_out(wait_result):
    """Normalize the channel adapter's timeout result for the MeTTa policy."""
    return 1 if str(wait_result).startswith("rested ") else 0
