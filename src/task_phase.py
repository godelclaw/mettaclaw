"""Witnessed, monotone task-phase world state.

The store is replaceable policy outside the Iter process kernel. It imposes
no global phase order: phases may be activated independently. Its single hard
fact is that witnessed completion cannot silently become pending or active
again within the same task instance.
"""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import tempfile


SCHEMA = 1
_RANK = {"pending": 0, "active": 1, "completed": 2}


def _path() -> Path | None:
    raw = os.environ.get("METTACLAW_TASK_PHASE_PATH", "").strip()
    return Path(raw) if raw else None


@contextmanager
def _locked(path: Path):
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        state = (json.loads(path.read_text(encoding="utf-8"))
                 if path.is_file() else None)
        yield state
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _write(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=path.name + ".", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def initialize(task_id: str, phases=(), evidence_revision: str = "initial",
               path: Path | None = None) -> dict:
    path = path or _path()
    if path is None:
        raise RuntimeError("task phase store is not configured")
    task_id = str(task_id).strip()
    if not task_id:
        raise ValueError("task_id must be nonempty")
    with _locked(path) as current:
        if current is not None:
            if current.get("task_id") != task_id:
                raise ValueError("task phase store belongs to another task")
            return current
        state = {
            "schema": SCHEMA,
            "task_id": task_id,
            "evidence_revision": str(evidence_revision),
            "revision": 0,
            "phases": {
                str(phase): {"status": "pending", "evidence": None}
                for phase in phases
            },
        }
        _write(path, state)
        return state


def transition(phase: str, status: str, evidence_revision: str,
               evidence_ref: str | None = None,
               path: Path | None = None) -> str:
    """Advance one phase under a monotone, witnessed transition."""

    path = path or _path()
    if path is None:
        return "TASK_PHASE_DISABLED"
    phase = str(phase).strip()
    status = str(status).strip()
    if not phase or status not in _RANK:
        raise ValueError("invalid task phase transition")
    if status == "completed" and not str(evidence_ref or "").strip():
        raise ValueError("completion requires an evidence reference")
    with _locked(path) as state:
        if state is None:
            raise RuntimeError("task phase store is not initialized")
        phases = state.setdefault("phases", {})
        previous = phases.get(phase, {"status": "pending", "evidence": None})
        previous_status = previous.get("status", "pending")
        if previous_status not in _RANK:
            raise ValueError("task phase store has an invalid status")
        if _RANK[status] < _RANK[previous_status]:
            return "WITHHELD_PHASE_REGRESSION"
        if previous_status == "completed":
            return "PHASE_ALREADY_COMPLETED"
        phases[phase] = {
            "status": status,
            "evidence": (str(evidence_ref) if status == "completed" else None),
        }
        state["evidence_revision"] = str(evidence_revision)
        state["revision"] = int(state.get("revision", 0)) + 1
        _write(path, state)
    return "PHASE_ADVANCED"


def snapshot(path: Path | None = None) -> dict | None:
    path = path or _path()
    if path is None or not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise ValueError("task phase store has an unsupported schema")
    return value


def view() -> str:
    state = snapshot()
    if state is None:
        return ""
    phases = state.get("phases", {})
    if not isinstance(phases, dict):
        raise ValueError("task phase map must be an object")
    active = sorted(
        phase for phase, value in phases.items()
        if isinstance(value, dict) and value.get("status") == "active"
    )
    completed = sorted(
        phase for phase, value in phases.items()
        if isinstance(value, dict) and value.get("status") == "completed"
    )
    pending = sorted(
        phase for phase, value in phases.items()
        if isinstance(value, dict) and value.get("status") == "pending"
    )
    phase = active[0] if len(active) == 1 else (
        "completed" if completed and not active and not pending else "plural"
    )
    return (
        "task=%s phase=%s revision=%s evidence-revision=%s "
        "active=%s completed=%s pending=%s"
        % (state.get("task_id", "?"), phase, state.get("revision", 0),
           state.get("evidence_revision", "?"),
           json.dumps(active, ensure_ascii=False),
           json.dumps(completed, ensure_ascii=False),
           json.dumps(pending, ensure_ascii=False))
    )
