"""Small fsync-capable hash-chained JSONL log."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import threading
import uuid


ZERO_HASH = "0" * 64


class DurableLogError(RuntimeError):
    pass


class DurableLogCorruption(DurableLogError):
    pass


class DurableLogConfigurationMismatch(DurableLogError):
    pass


@dataclass(frozen=True)
class ChainVerification:
    valid: bool
    event_count: int
    last_hash: str
    generation_id: str | None = None
    fingerprint: str | None = None
    error_line: int | None = None
    error: str | None = None


def canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def fingerprint(value):
    digest = hashlib.sha256(canonical_json(value).encode("utf-8"))
    return "sha256:" + digest.hexdigest()


def event_hash(event):
    unhashed = dict(event)
    unhashed.pop("event_hash", None)
    return hashlib.sha256(canonical_json(unhashed).encode("utf-8")).hexdigest()


def verify_chain(path, *, schema, fingerprint_field):
    path = Path(path)
    if not path.exists():
        return ChainVerification(
            False, 0, ZERO_HASH, error="journal does not exist"
        )

    previous_hash = ZERO_HASH
    event_count = 0
    generation_id = None
    generation_fingerprint = None
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, 1):
                if not raw_line.endswith("\n"):
                    return ChainVerification(
                        False,
                        event_count,
                        previous_hash,
                        generation_id,
                        generation_fingerprint,
                        line_number,
                        "truncated final line",
                    )
                try:
                    event = json.loads(raw_line)
                except json.JSONDecodeError:
                    return ChainVerification(
                        False,
                        event_count,
                        previous_hash,
                        generation_id,
                        generation_fingerprint,
                        line_number,
                        "invalid JSON",
                    )
                if not isinstance(event, dict):
                    error = "event must be an object"
                elif event.get("schema") != schema:
                    error = "unsupported schema"
                elif event.get("sequence") != event_count:
                    error = "non-contiguous sequence"
                elif event.get("prev_event_hash") != previous_hash:
                    error = "previous hash mismatch"
                elif event.get("event_hash") != event_hash(event):
                    error = "event hash mismatch"
                elif event_count == 0 and event.get("event_type") != "Generation":
                    error = "first event must be Generation"
                elif event_count > 0 and event.get("event_type") == "Generation":
                    error = "Generation may appear only once"
                else:
                    error = None
                if error:
                    return ChainVerification(
                        False,
                        event_count,
                        previous_hash,
                        generation_id,
                        generation_fingerprint,
                        line_number,
                        error,
                    )
                if event_count == 0:
                    generation_id = event.get("generation_id")
                    generation_fingerprint = event.get(fingerprint_field)
                    if not isinstance(generation_id, str) or not generation_id:
                        return ChainVerification(
                            False,
                            0,
                            ZERO_HASH,
                            error_line=line_number,
                            error="Generation lacks generation_id",
                        )
                    if (
                        not isinstance(generation_fingerprint, str)
                        or not generation_fingerprint
                    ):
                        return ChainVerification(
                            False,
                            0,
                            ZERO_HASH,
                            generation_id,
                            error_line=line_number,
                            error=f"Generation lacks {fingerprint_field}",
                        )
                previous_hash = event["event_hash"]
                event_count += 1
    except OSError as exc:
        return ChainVerification(
            False,
            event_count,
            previous_hash,
            generation_id,
            generation_fingerprint,
            error=str(exc),
        )

    if event_count == 0:
        return ChainVerification(False, 0, ZERO_HASH, error="journal is empty")
    return ChainVerification(
        True,
        event_count,
        previous_hash,
        generation_id,
        generation_fingerprint,
    )


def read_verified_events(path, *, schema, fingerprint_field):
    verification = verify_chain(
        path, schema=schema, fingerprint_field=fingerprint_field
    )
    if not verification.valid:
        raise DurableLogCorruption(
            f"line {verification.error_line}: {verification.error}"
        )
    with Path(path).open("r", encoding="utf-8") as handle:
        return tuple(json.loads(line) for line in handle)


class HashChainLog:
    def __init__(
        self,
        path,
        *,
        schema,
        fingerprint_field,
        expected_fingerprint,
        generation_payload,
        fsync=True,
        clock,
        uuid_factory=uuid.uuid4,
    ):
        self.path = Path(path)
        self.schema = str(schema)
        self.fingerprint_field = str(fingerprint_field)
        self.expected_fingerprint = str(expected_fingerprint)
        self.fsync = bool(fsync)
        self.clock = clock
        self.uuid_factory = uuid_factory
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and self.path.stat().st_size:
            verification = self.verify()
            if not verification.valid:
                raise DurableLogCorruption(
                    f"line {verification.error_line}: {verification.error}"
                )
            if verification.fingerprint != self.expected_fingerprint:
                raise DurableLogConfigurationMismatch(
                    "generation fingerprint does not match configuration"
                )
            self._sequence = verification.event_count
            self._last_hash = verification.last_hash
            self.generation_id = verification.generation_id
        else:
            self._sequence = 0
            self._last_hash = ZERO_HASH
            self.generation_id = str(self.uuid_factory())
            self._append_unlocked(
                {
                    "event_type": "Generation",
                    "generation_id": self.generation_id,
                    "created_at": self.clock(),
                    self.fingerprint_field: self.expected_fingerprint,
                    **dict(generation_payload),
                }
            )

    def _append_unlocked(self, payload):
        event = {
            "schema": self.schema,
            "sequence": self._sequence,
            "prev_event_hash": self._last_hash,
            **dict(payload),
        }
        event["event_hash"] = event_hash(event)
        encoded = (canonical_json(event) + "\n").encode("utf-8")
        new_file = not self.path.exists()
        descriptor = os.open(
            self.path,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY | os.O_CLOEXEC,
            0o660,
        )
        with os.fdopen(descriptor, "ab", closefd=True) as handle:
            handle.write(encoded)
            handle.flush()
            if self.fsync:
                os.fsync(handle.fileno())
        if new_file and self.fsync:
            directory = os.open(
                self.path.parent,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        self._sequence += 1
        self._last_hash = event["event_hash"]
        return event

    def append(self, payload):
        with self._lock:
            return self._append_unlocked(payload)

    def verify(self):
        return verify_chain(
            self.path,
            schema=self.schema,
            fingerprint_field=self.fingerprint_field,
        )

    def events(self):
        return read_verified_events(
            self.path,
            schema=self.schema,
            fingerprint_field=self.fingerprint_field,
        )
