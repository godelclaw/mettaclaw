"""Small, replaceable declaration of the queries a context must answer."""

from __future__ import annotations

import json
import os
from pathlib import Path


BASE_QUERIES = (
    "operator-stimulus",
    "active-goals",
    "task-phase",
    "effect-outcomes",
    "source-currentness",
)


def load() -> tuple[str, ...]:
    """Return stable query names, optionally extended by a JSON list.

    The file is policy data. Its absence leaves the protected baseline in
    place; malformed content is unavailable evidence and therefore raises.
    """

    raw = os.environ.get("METTACLAW_ACTIVE_QUERIES_PATH", "").strip()
    additions = []
    if raw:
        value = json.loads(Path(raw).read_text(encoding="utf-8"))
        if not isinstance(value, list) or not all(
                isinstance(item, str) and item.strip() for item in value):
            raise ValueError("active query file must contain a JSON string list")
        additions = [item.strip() for item in value]
    return tuple(dict.fromkeys((*BASE_QUERIES, *additions)))


def view() -> str:
    return json.dumps(load(), ensure_ascii=False, separators=(",", ":"))


def from_observations(observations) -> tuple[str, ...]:
    for item in observations:
        if (item.source_id == "active-query-declaration"
                and item.status in ("known", "stale-known")):
            value = json.loads(item.text)
            if isinstance(value, list) and all(isinstance(q, str) for q in value):
                return tuple(dict.fromkeys(value))
    return BASE_QUERIES
