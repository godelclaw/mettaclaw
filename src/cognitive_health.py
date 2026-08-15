"""Durable, privacy-safe receipts for model turns.

The agent loop records an obligation before its governance gate. The model
adapter then records start, success, or failure. A pending obligation keeps
its original timestamp: repeated empty ticks therefore cannot make a stalled
mind look fresh.
"""

import json
import os
import tempfile
import threading
import time


_lock = threading.RLock()


def _path():
    configured = os.environ.get("METTACLAW_COGNITIVE_HEALTH_PATH", "")
    if configured:
        return configured
    state_home = os.environ.get(
        "XDG_STATE_HOME", os.path.expanduser("~/.local/state"))
    instance = os.environ.get("METTACLAW_INSTANCE", "default")
    return os.path.join(state_home, "pettaclaw", instance,
                        "cognitive-health.json")


def _read():
    try:
        with open(_path(), encoding="utf-8") as stream:
            value = json.load(stream)
        return value if isinstance(value, dict) else {}
    except (OSError, TypeError, ValueError):
        return {}


def _write(value):
    path = _path()
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".cognitive-health-",
                                     dir=parent, text=True)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=True, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _label(value, default="unknown"):
    text = str(value or default).strip().lower()
    safe = "".join(c for c in text if c.isalnum() or c in "-_")
    return (safe or default)[:64]


def _stamp(now):
    return time.time() if now is None else float(now)


def expect_turn(mode="unknown", budget=None, now=None):
    """Record a model-turn obligation without refreshing an older one."""
    now = _stamp(now)
    try:
        budget = None if budget is None else max(0, int(budget))
    except (TypeError, ValueError):
        budget = None
    try:
        with _lock:
            value = _read()
            if not float(value.get("pending_since", 0) or 0):
                value["pending_since"] = now
            value.update({
                "schema": 1,
                "last_expected_at": now,
                "expected_count": int(value.get("expected_count", 0)) + 1,
                "mode": _label(mode),
            })
            if budget is not None:
                value["budget_at_start"] = budget
            _write(value)
        return 1
    except Exception:
        return 0


def turn_started(provider="unknown", now=None):
    """Record entry into a provider call, defensively creating an obligation."""
    now = _stamp(now)
    try:
        with _lock:
            value = _read()
            if not float(value.get("pending_since", 0) or 0):
                value["pending_since"] = now
            value.update({
                "schema": 1,
                "last_started_at": now,
                "started_count": int(value.get("started_count", 0)) + 1,
                "provider": _label(provider),
            })
            _write(value)
        return 1
    except Exception:
        return 0


def turn_completed(response_bytes=0, now=None):
    """Discharge the current obligation after a non-empty model answer."""
    now = _stamp(now)
    try:
        size = max(0, int(response_bytes))
    except (TypeError, ValueError):
        size = 0
    try:
        with _lock:
            value = _read()
            value.update({
                "schema": 1,
                "pending_since": 0,
                "last_completed_at": now,
                "completed_count": int(value.get("completed_count", 0)) + 1,
                "last_response_bytes": size,
                "last_outcome": "completed",
            })
            _write(value)
        return 1
    except Exception:
        return 0


def turn_failed(kind="provider-error", now=None):
    """Record failure while leaving the original obligation outstanding."""
    now = _stamp(now)
    try:
        with _lock:
            value = _read()
            if not float(value.get("pending_since", 0) or 0):
                value["pending_since"] = now
            value.update({
                "schema": 1,
                "last_failed_at": now,
                "failed_count": int(value.get("failed_count", 0)) + 1,
                "last_failure_type": _label(kind, "provider-error"),
                "last_outcome": "failed",
            })
            _write(value)
        return 1
    except Exception:
        return 0


def snapshot():
    """Return the receipt state; it contains no prompt or response text."""
    with _lock:
        return dict(_read())
