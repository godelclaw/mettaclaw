"""Deterministic receipts for one bounded context projection.

The certificate identifies the evidence revision and exact projection shown
to the model. It does not authorize effects or choose an action. SHA-256 is
an engineering identity check, not a formal collision-freedom claim.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Iterable


SCHEMA = 1


@dataclass(frozen=True)
class SourceRef:
    source_id: str
    status: str
    revision: str


@dataclass(frozen=True)
class ContextCertificate:
    schema: int
    evidence_revision: str
    active_queries: tuple[str, ...]
    commitment_phase: str
    sources: tuple[SourceRef, ...]
    projection_receipt: str

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "evidence_revision": self.evidence_revision,
            "active_queries": list(self.active_queries),
            "commitment_phase": self.commitment_phase,
            "sources": [asdict(source) for source in self.sources],
            "projection_receipt": self.projection_receipt,
        }


def _canonical(value) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8", "replace")


def _digest(value) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def evidence_revision(observations: Iterable) -> str:
    refs = [
        {
            "source_id": item.source_id,
            "status": item.status,
            "revision": item.revision,
        }
        for item in observations
    ]
    return _digest({"schema": SCHEMA, "sources": refs})


def phase_from_observations(observations: Iterable) -> str:
    """Prefer generic task phase, then the legacy commitment projection."""

    observations = tuple(observations)
    for wanted in ("task-phase", "commitment-state"):
        for item in observations:
            if item.source_id != wanted or item.status not in (
                    "known", "stale-known"):
                continue
            for token in str(item.text).split():
                if token.startswith("phase="):
                    return token.partition("=")[2]
    return "unavailable"


def issue(observations: Iterable, active_queries: Iterable[str],
          rendered_projection: str) -> ContextCertificate:
    observations = tuple(observations)
    queries = tuple(dict.fromkeys(str(query) for query in active_queries))
    sources = tuple(
        SourceRef(item.source_id, item.status, item.revision)
        for item in observations
    )
    revision = evidence_revision(observations)
    phase = phase_from_observations(observations)
    payload = {
        "schema": SCHEMA,
        "evidence_revision": revision,
        "active_queries": queries,
        "commitment_phase": phase,
        "sources": [asdict(source) for source in sources],
        "projection": str(rendered_projection),
    }
    return ContextCertificate(
        schema=SCHEMA,
        evidence_revision=revision,
        active_queries=queries,
        commitment_phase=phase,
        sources=sources,
        projection_receipt=_digest(payload),
    )


def render(certificate: ContextCertificate) -> str:
    return "CONTEXT_CERTIFICATE " + json.dumps(
        certificate.to_dict(), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    )
