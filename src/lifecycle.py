"""Fail-closed operator authority for Gödel's cognitive lifecycle.

The process may remain alive as a lightweight Telegram control plane while
cognition is stopped.  Cognition is authorized only when the durable latch is
``running`` *and* the external deployment-watch timer is active.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time


STOPPED = "stopped"
RUNNING = "running"
_lock = threading.RLock()


def _path() -> Path:
    configured = os.environ.get("METTACLAW_LIFECYCLE_PATH", "")
    if configured:
        return Path(configured)
    state_home = os.environ.get(
        "XDG_STATE_HOME", os.path.expanduser("~/.local/state")
    )
    instance = os.environ.get("METTACLAW_INSTANCE", "pettaclaw-godel")
    return Path(state_home) / instance / "lifecycle.json"


def _watch_service() -> str:
    return os.environ.get(
        "METTACLAW_DEPLOYMENT_WATCH_SERVICE",
        "godel-deployment-watch.service",
    )


def _watch_timer() -> str:
    return os.environ.get(
        "METTACLAW_DEPLOYMENT_WATCH_TIMER",
        "godel-deployment-watch.timer",
    )


def _deployment_path() -> Path:
    configured = os.environ.get("METTACLAW_DEPLOYMENT_STATE_PATH", "")
    if configured:
        return Path(configured)
    state_home = os.environ.get(
        "XDG_STATE_HOME", os.path.expanduser("~/.local/state")
    )
    instance = os.environ.get("METTACLAW_INSTANCE", "pettaclaw-godel")
    return Path(state_home) / instance / "deployment.json"


def _read() -> str:
    try:
        value = json.loads(_path().read_text(encoding="utf-8"))
        if value == {"schema": 1, "state": RUNNING}:
            return RUNNING
        if value == {"schema": 1, "state": STOPPED}:
            return STOPPED
    except (OSError, TypeError, ValueError):
        pass
    return STOPPED


def _write(state: str) -> None:
    if state not in (STOPPED, RUNNING):
        raise ValueError("invalid lifecycle state")
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".lifecycle-", dir=path.parent, text=True
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"schema": 1, "state": state}, stream,
                      sort_keys=True)
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


def _systemctl(*arguments: str) -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["systemctl", "--user", *arguments],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode, (result.stdout or result.stderr).strip()
    except (OSError, subprocess.SubprocessError) as error:
        return 1, "%s: %s" % (type(error).__name__, error)


def watcher_active() -> bool:
    code, output = _systemctl("is-active", _watch_timer())
    return code == 0 and output == "active"


def _fresh_probe_healthy(since: float) -> tuple[bool, str]:
    try:
        deployment = json.loads(
            _deployment_path().read_text(encoding="utf-8")
        )
        observation = deployment.get("last_observation") or {}
        observed_at = float(observation.get("observed_at", 0) or 0)
        candidate = str(deployment.get("candidate", ""))
        head = str(observation.get("head", ""))
        problems = observation.get("problems")
        active = observation.get("active") is True
        if observed_at < since:
            return False, "watcher observation is not fresh"
        if not candidate or head != candidate:
            return False, "watcher observed the wrong generation"
        if not active:
            return False, "watcher did not observe the control plane active"
        if problems != []:
            names = ",".join(str(item) for item in (problems or []))
            return False, "watcher reported problems" + (
                ": " + names if names else ""
            )
        return True, "healthy"
    except (OSError, TypeError, ValueError):
        return False, "watcher observation is missing or invalid"


def durable_state() -> str:
    with _lock:
        return _read()


def cognition_enabled() -> int:
    """Numeric flag for MeTTa: authority requires latch AND watcher."""
    with _lock:
        return int(_read() == RUNNING and watcher_active())


def view() -> str:
    with _lock:
        state = _read()
        watching = watcher_active()
    if state == RUNNING and watching:
        return "running (deployment watcher active)"
    if state == RUNNING:
        return "stopped (watcher unavailable; fail-closed)"
    return "stopped (operator latch)"


def stop() -> str:
    """Revoke cognition first, then remove every automatic-revival path."""
    with _lock:
        _write(STOPPED)
        timer_code, timer_output = _systemctl(
            "disable", "--now", _watch_timer()
        )
        service_code, service_output = _systemctl(
            "stop", _watch_service()
        )
        watching = watcher_active()
    if watching:
        return "stop incomplete: cognition revoked, but watcher is still active"
    if timer_code not in (0, 1) or service_code not in (0, 5):
        detail = timer_output or service_output or "systemctl failed"
        return "stopped fail-closed; watcher shutdown reported: " + detail
    return "stopped: cognition revoked; deployment watcher inactive"


def start() -> str:
    """Start and verify the watcher before granting cognitive authority."""
    with _lock:
        # Every failure prefix stays stopped, including a prior running state.
        _write(STOPPED)
        _systemctl("unmask", _watch_service(), _watch_timer())
        code, output = _systemctl("enable", "--now", _watch_timer())
        if code != 0 or not watcher_active():
            return (
                "start refused: cognition remains stopped; deployment "
                "watcher did not become active"
                + (" (" + output + ")" if output else "")
            )
        probe_started = time.time()
        probe_code, probe_output = _systemctl("start", _watch_service())
        probe_healthy, probe_detail = _fresh_probe_healthy(probe_started)
        if probe_code != 0 or not probe_healthy:
            _systemctl("disable", "--now", _watch_timer())
            return (
                "start refused: cognition remains stopped; deployment "
                "watcher probe was not healthy ("
                + (probe_detail or probe_output or "unknown failure") + ")"
            )
        _write(RUNNING)
    return "started: deployment watcher active; cognition enabled"
