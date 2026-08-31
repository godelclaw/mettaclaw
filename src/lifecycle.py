"""Operator authority for Gödel's cognitive lifecycle.

The process may remain alive as a lightweight Telegram control plane while
cognition is stopped.  The durable operator latch alone authorizes cognition;
the external deployment watcher observes health but cannot silently disable
the agent.
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


def _watcher_lease_seconds() -> int:
    try:
        return max(30, int(float(os.environ.get(
            "METTACLAW_WATCHER_LEASE_SECONDS", "150"
        ))))
    except (TypeError, ValueError):
        return 150


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


def watcher_lease_healthy(now: float | None = None) -> bool:
    """Read the watcher's bounded receipt without spawning a subprocess.

    The minute timer refreshes the deployment observation.  A dead watcher
    therefore loses authority after one explicit lease instead of making every
    model turn and `/activity` call synchronously query systemd.
    """
    now = time.time() if now is None else float(now)
    healthy, _detail = _fresh_probe_healthy(
        now - _watcher_lease_seconds()
    )
    return healthy


def durable_state() -> str:
    with _lock:
        return _read()


def cognition_enabled() -> int:
    """Numeric flag for MeTTa: only the durable operator latch has authority."""
    with _lock:
        return int(_read() == RUNNING)


def view() -> str:
    with _lock:
        state = _read()
    if state == RUNNING:
        return "running (operator latch)"
    return "stopped (operator latch)"


def stop() -> str:
    """Revoke cognition through the durable operator latch only."""
    with _lock:
        _write(STOPPED)
    return "stopped: cognition revoked by operator latch"


def start() -> str:
    """Grant cognition through the durable operator latch only."""
    with _lock:
        _write(RUNNING)
    return "started: cognition enabled by operator latch"
