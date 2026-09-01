"""Small cross-runtime witness for between-effect stimulus checks.

The live PeTTa bridge can query Telegram in-process.  CeTTa's imported Prolog
module deliberately cannot call Python, so the broker also publishes the same
three integers through one atomic text record.  This is projection, not a new
control state: Telegram/shadow epochs remain authoritative.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Any


SCHEMA = 1


def path() -> Path | None:
    raw = os.environ.get("METTACLAW_STIMULUS_FRONTIER_PATH", "").strip()
    return Path(raw) if raw else None


def publish(turn: Any, captured_epoch: Any, live_epoch: Any) -> bool:
    target = path()
    if target is None:
        return False
    values = (SCHEMA, int(turn), int(captured_epoch), int(live_epoch))
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=target.name + ".", dir=target.parent
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="ascii") as stream:
            stream.write("%d %d %d %d\n" % values)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return True


def read() -> tuple[int, int, int] | None:
    target = path()
    if target is None:
        return None
    try:
        words = target.read_text(encoding="ascii").split()
        schema, turn, captured, live = (int(word) for word in words)
    except (OSError, ValueError, TypeError):
        return None
    if schema != SCHEMA:
        return None
    return turn, captured, live


def stimulus_free(turn: Any) -> int:
    record = read()
    if record is None:
        return 0
    recorded_turn, captured, live = record
    return int(recorded_turn == int(turn) and captured == live)
