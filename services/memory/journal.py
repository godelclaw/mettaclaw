"""Append-only canonical memory journal with hash-chain verification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import uuid

from services.durable_log import (
    DurableLogConfigurationMismatch,
    DurableLogCorruption,
    HashChainLog,
    ZERO_HASH,
    fingerprint,
    verify_chain,
)


SCHEMA = "cettaclaw-memory-journal-v1"
PRIVACY_CLASS = "live-memory-private"
FINGERPRINT_FIELD = "embedding_fingerprint"


class JournalError(RuntimeError):
    pass


class JournalCorruption(JournalError):
    pass


class JournalConfigurationMismatch(JournalError):
    pass


@dataclass(frozen=True)
class Verification:
    valid: bool
    event_count: int
    last_hash: str
    generation_id: str | None = None
    embedding_fingerprint: str | None = None
    error_line: int | None = None
    error: str | None = None

    def as_dict(self):
        return {
            "valid": self.valid,
            "event_count": self.event_count,
            "last_hash": self.last_hash,
            "generation_id": self.generation_id,
            "embedding_fingerprint": self.embedding_fingerprint,
            "error_line": self.error_line,
            "error": self.error,
        }


def embedding_fingerprint(metadata):
    return fingerprint(dict(metadata))


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _memory_verification(result):
    return Verification(
        result.valid,
        result.event_count,
        result.last_hash,
        result.generation_id,
        result.fingerprint,
        result.error_line,
        result.error,
    )


def verify_journal(path):
    return _memory_verification(
        verify_chain(
            path,
            schema=SCHEMA,
            fingerprint_field=FINGERPRINT_FIELD,
        )
    )


class MemoryJournal:
    def __init__(
        self,
        path,
        embedding_metadata,
        *,
        fsync=True,
        clock=_utc_now,
        uuid_factory=uuid.uuid4,
    ):
        self.path = path
        self.embedding_metadata = dict(embedding_metadata)
        self.embedding_fingerprint = embedding_fingerprint(
            self.embedding_metadata
        )
        try:
            self._chain = HashChainLog(
                path,
                schema=SCHEMA,
                fingerprint_field=FINGERPRINT_FIELD,
                expected_fingerprint=self.embedding_fingerprint,
                generation_payload={
                    "embedding": self.embedding_metadata,
                    "privacy_class": PRIVACY_CLASS,
                    "index_is_rebuildable": False,
                },
                fsync=fsync,
                clock=clock,
                uuid_factory=uuid_factory,
            )
        except DurableLogCorruption as exc:
            raise JournalCorruption(str(exc)) from exc
        except DurableLogConfigurationMismatch as exc:
            raise JournalConfigurationMismatch(str(exc)) from exc
        self.generation_id = self._chain.generation_id
        self.fsync = bool(fsync)
        self.clock = clock
        self.uuid_factory = uuid_factory

    def append_remember(
        self,
        content,
        *,
        memory_id=None,
        timestamp=None,
        collection="memories",
    ):
        if not isinstance(content, str) or not content:
            raise ValueError("content must be a non-empty string")
        memory_id = str(memory_id or self.uuid_factory())
        timestamp = str(timestamp or self.clock())
        return self._chain.append(
            {
                "event_type": "Remember",
                "event_id": str(self.uuid_factory()),
                "memory_id": memory_id,
                "time": timestamp,
                "collection": str(collection),
                "content": content,
            }
        )

    def verify(self):
        return _memory_verification(self._chain.verify())
