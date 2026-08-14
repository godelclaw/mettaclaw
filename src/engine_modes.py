"""Persistent evaluator selection shared by the launcher and operator UI."""

import os
import threading
import time


ENGINES = {
    "petta": "SWI-PeTTa; stable default",
    "cetta": "CeTTa running the PeTTa language profile",
    "pleatta": "PLeaTTa host runtime",
}

ALIASES = {
    "swi": "petta",
    "swi-petta": "petta",
}

_lock = threading.RLock()


def _canonical(name):
    name = str(name or "").strip().lower()
    return ALIASES.get(name, name)


def _state_path():
    configured = os.environ.get("METTACLAW_ENGINE_STATE_PATH", "")
    if configured:
        return configured
    state_home = os.environ.get(
        "XDG_STATE_HOME", os.path.expanduser("~/.local/state"))
    instance = os.environ.get("METTACLAW_INSTANCE", "default")
    return os.path.join(state_home, instance, "engine")


def _engine_paths(name):
    home = os.path.expanduser("~")
    if name == "petta":
        root = os.environ.get("PETTA_ROOT", os.path.join(home, "repos", "PeTTa"))
        return (os.path.join(root, "run.sh"),)
    if name == "cetta":
        root = os.environ.get("CETTA_ROOT", os.path.join(home, "repos", "CeTTa"))
        return (os.environ.get("CETTA_BIN", os.path.join(root, "cetta")),)
    root = os.environ.get(
        "PLEATTA_ROOT", os.path.join(home, "repos", "LeaTTa-petta"))
    return (
        os.environ.get(
            "PLEATTA_BIN", os.path.join(root, ".lake", "build", "bin", "pleatta")),
        os.environ.get(
            "PLEATTA_PY_WORKER",
            os.path.join(root, "scripts", "pleatta-python-worker.py")),
    )


def engine_available(name):
    name = _canonical(name)
    if name not in ENGINES:
        return False
    paths = _engine_paths(name)
    for index, path in enumerate(paths):
        if not os.path.isfile(path):
            return False
        if index == 0 and not os.access(path, os.X_OK):
            return False
    return bool(paths)


def selected_engine():
    fallback = _canonical(os.environ.get("METTACLAW_ENGINE", "petta"))
    if fallback not in ENGINES:
        fallback = "petta"
    try:
        with open(_state_path(), "r", encoding="utf-8") as stream:
            selected = _canonical(stream.readline())
    except OSError:
        selected = fallback
    return selected if selected in ENGINES else "petta"


def active_engine():
    active = _canonical(os.environ.get(
        "METTACLAW_ACTIVE_ENGINE",
        os.environ.get("METTACLAW_ENGINE", "petta")))
    return active if active in ENGINES else "petta"


def engine_view():
    active = active_engine()
    selected = selected_engine()
    suffix = ""
    if selected != active:
        suffix = "; requested %s for next process" % selected
    return "active engine: %s — %s%s" % (
        active, ENGINES[active], suffix)


def engines_view():
    active = active_engine()
    selected = selected_engine()
    lines = []
    for name, description in ENGINES.items():
        marks = []
        if name == active:
            marks.append("active")
        if name == selected and name != active:
            marks.append("requested")
        if not engine_available(name):
            marks.append("unavailable")
        prefix = "● " if name == active else "  "
        state = " [%s]" % ", ".join(marks) if marks else ""
        lines.append(prefix + name + state + " — " + description)
    return "\n".join(lines)


def _save(name):
    path = _state_path()
    parent = os.path.dirname(path)
    try:
        if parent:
            os.makedirs(parent, exist_ok=True)
        temporary = "%s.tmp.%d" % (path, os.getpid())
        with open(temporary, "w", encoding="utf-8") as stream:
            stream.write(name + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        return True
    except OSError as exc:
        print("[engine-mode] save failed:", type(exc).__name__)
        return False


def set_engine(name):
    requested = str(name or "").strip().lower()
    name = _canonical(requested)
    if name not in ENGINES:
        return "engine-set failed: choose one of %s" % ", ".join(ENGINES)
    if not engine_available(name):
        return "engine-set failed: %s is unavailable" % name
    with _lock:
        if not _save(name):
            return "engine-set failed: could not persist"
    alias = " (from alias '%s')" % requested if requested != name else ""
    if name == active_engine():
        return "engine '%s' is already active%s" % (name, alias)
    return "engine set to '%s'%s; recycling into it" % (name, alias)


def request_recycle():
    path = os.environ.get("METTACLAW_RECYCLE_REQUEST_PATH", "")
    if not path:
        return False
    parent = os.path.dirname(path)
    temporary = "%s.tmp.%d" % (path, os.getpid())
    try:
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(temporary, "w", encoding="utf-8") as stream:
            stream.write("requested_at=%.6f reason=engine-switch\n" % time.time())
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        return True
    except OSError as exc:
        print("[engine-mode] recycle request failed:", type(exc).__name__)
        return False
