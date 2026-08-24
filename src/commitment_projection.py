"""Bounded, read-only projection of a receipt-derived task commitment."""

from __future__ import annotations

import json
import os
from pathlib import Path


ALLOWED_PHASES = {
    "need-create", "need-launch", "need-trust", "need-server",
    "goal-satisfied", "stopped",
}


def view() -> str:
    raw = os.environ.get("METTACLAW_COMMITMENT_STATE_PATH", "")
    if not raw:
        return ""
    path = Path(raw)
    if not path.exists():
        return ""
    state = json.loads(path.read_text(encoding="utf-8"))
    phase = state.get("phase")
    if phase not in ALLOWED_PHASES:
        raise ValueError("commitment state has an unknown phase")
    revision = int(state.get("revision", state.get("effects", 0)))
    finished = bool(state.get("finished", False))
    return "phase=%s revision=%d finished=%s" % (
        phase, revision, str(finished).lower()
    )
