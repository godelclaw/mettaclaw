"""Read-only projection of pending source proposals and active Iter programs.

Proposal readiness is not activation.  This view keeps the two namespaces
separate and exposes only content identities needed by a later context
certificate; it grants no promotion or filesystem authority.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re


_PROPOSAL_ID = re.compile(r"^[0-9a-f]{64}$")


def _proposal_store() -> Path:
    configured = os.environ.get("METTACLAW_SELFMOD_PROPOSAL_STORE", "").strip()
    if configured:
        return Path(configured)
    module_root = Path(__file__).resolve().parents[1]
    state_home = Path(
        os.environ.get(
            "XDG_STATE_HOME", Path.home() / ".local" / "state"
        )
    )
    instance = os.environ.get("METTACLAW_INSTANCE", module_root.name)
    return state_home / instance / "selfmod-proposals"


def _pending_proposals() -> dict:
    store = _proposal_store()
    if not store.is_dir() or store.is_symlink():
        return {"state": "absent", "pending": [], "invalid_count": 0}
    pending = []
    invalid = 0
    for proposal in sorted(store.iterdir(), key=lambda path: path.name):
        if not proposal.is_dir() or proposal.is_symlink():
            continue
        if not _PROPOSAL_ID.fullmatch(proposal.name):
            invalid += 1
            continue
        manifest_path = proposal / "manifest.json"
        promotion_path = proposal / "promotion.json"
        if promotion_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            invalid += 1
            continue
        if not isinstance(manifest, dict):
            invalid += 1
            continue
        pending.append({
            "proposal_id": proposal.name,
            "state": str(manifest.get("state", "unknown")),
            "operation": str(manifest.get("operation", "unknown")),
            "target": str(manifest.get("target", "")),
            "candidate_sha256": str(manifest.get("candidate_sha256", "")),
            "syntax": str((manifest.get("syntax") or {}).get("status", "unknown")),
            "semantic": str(
                (manifest.get("semantic") or {}).get("status", "unknown")
            ),
        })
    return {
        "state": "observed",
        "pending": pending,
        "invalid_count": invalid,
    }


def _iter_programs() -> dict:
    try:
        import iter_authoring

        observed = json.loads(iter_authoring.list_transformations())
        if not isinstance(observed, dict):
            raise ValueError("Iter inventory is not an object")
        return observed
    except Exception as error:
        return {
            "state": "unavailable",
            "error_kind": type(error).__name__,
        }


def view() -> str:
    """Render one deterministic development snapshot for model context."""

    return json.dumps(
        {
            "schema": 1,
            "protected_source_proposals": _pending_proposals(),
            "iter_transformations": _iter_programs(),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
