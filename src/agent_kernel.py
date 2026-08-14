"""One append-only causal ledger and its reconstructible projection.

Channel adapters and loop policies remain replaceable.  This module owns the
small common substrate they share: accepted inputs, committed effects, and the
latest working capsule.  File order is the causal order; ``index`` makes that
order explicit for receipts and diagnostics.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import threading
import time
import uuid


SCHEMA_VERSION = 1
_LOCK = threading.RLock()
_CACHE = {}


class EventLogError(RuntimeError):
    """The ledger is present but not a valid complete event prefix."""


def _path():
    return os.environ.get(
        "METTACLAW_EVENT_LOG_PATH", "memory/agent_events.jsonl")


def canonical_bytes(value):
    """Canonical UTF-8 JSON used by every payload digest."""
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _stable_event_id(kind, idempotency_key):
    material = (
        "mettaclaw-event-v1\x00" + str(kind) + "\x00" + str(idempotency_key)
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _validate_event(event, expected_index):
    if not isinstance(event, dict):
        raise EventLogError("event is not an object")
    if event.get("version") != SCHEMA_VERSION:
        raise EventLogError("unsupported event version")
    if event.get("index") != expected_index:
        raise EventLogError("non-contiguous event index")
    if not isinstance(event.get("id"), str) or not event["id"]:
        raise EventLogError("event id is missing")
    payload = event.get("payload")
    if event.get("payload_digest") != digest(payload):
        raise EventLogError("payload digest mismatch")


def _decode_complete_lines(raw, allow_truncated_tail=True):
    if not raw:
        return []
    complete = raw.endswith(b"\n")
    lines = raw.splitlines()
    if not complete:
        if not allow_truncated_tail:
            raise EventLogError("truncated final event")
        lines = lines[:-1]
    events = []
    seen = set()
    for index, line in enumerate(lines, 1):
        if not line.strip():
            raise EventLogError("blank event line")
        try:
            event = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise EventLogError("malformed complete event") from exc
        _validate_event(event, index)
        if event["id"] in seen:
            raise EventLogError("duplicate physical event id")
        seen.add(event["id"])
        events.append(event)
    return events


def read_events(path=None):
    path = str(path or _path())
    try:
        with open(path, "rb") as stream:
            return _decode_complete_lines(stream.read())
    except FileNotFoundError:
        return []


def _projection(events):
    result = {
        "count": 0,
        "last_index": 0,
        "event_ids": set(),
        "event_digests": {},
        "frontier": {},
        "effects": set(),
        "working_set": {},
    }
    for event in events:
        result["count"] += 1
        result["last_index"] = event["index"]
        result["event_ids"].add(event["id"])
        result["event_digests"][event["id"]] = event["payload_digest"]
        kind = event["kind"]
        conversation = event.get("conversation", "")
        if kind == "input.accepted" and conversation:
            result["frontier"][conversation] = event["id"]
        elif kind == "effect.committed":
            key = event["payload"].get("effect_key")
            if key:
                result["effects"].add(str(key))
        elif kind == "working_set.saved":
            state = event["payload"].get("state")
            if isinstance(state, dict):
                result["working_set"] = dict(state)
                saved_at = event["payload"].get("saved_at")
                if isinstance(saved_at, (int, float)):
                    result["working_set"]["saved_at"] = saved_at
    return result


def _extend_projection(projection, event):
    updated = {
        "count": projection["count"] + 1,
        "last_index": event["index"],
        "event_ids": set(projection["event_ids"]),
        "event_digests": dict(projection["event_digests"]),
        "frontier": dict(projection["frontier"]),
        "effects": set(projection["effects"]),
        "working_set": dict(projection["working_set"]),
    }
    updated["event_ids"].add(event["id"])
    updated["event_digests"][event["id"]] = event["payload_digest"]
    kind = event["kind"]
    conversation = event.get("conversation", "")
    if kind == "input.accepted" and conversation:
        updated["frontier"][conversation] = event["id"]
    elif kind == "effect.committed":
        key = event["payload"].get("effect_key")
        if key:
            updated["effects"].add(str(key))
    elif kind == "working_set.saved":
        state = event["payload"].get("state")
        if isinstance(state, dict):
            updated["working_set"] = dict(state)
            saved_at = event["payload"].get("saved_at")
            if isinstance(saved_at, (int, float)):
                updated["working_set"]["saved_at"] = saved_at
    return updated


def project(path=None):
    """Rebuild the deterministic kernel projection from the ledger."""
    return _projection(read_events(path))


def _repair_truncated_tail(stream):
    stream.seek(0, os.SEEK_END)
    end = stream.tell()
    if end == 0:
        return
    stream.seek(end - 1)
    if stream.read(1) == b"\n":
        return
    position = end
    while position > 0:
        size = min(65536, position)
        position -= size
        stream.seek(position)
        chunk = stream.read(size)
        newline = chunk.rfind(b"\n")
        if newline >= 0:
            stream.truncate(position + newline + 1)
            return
    stream.truncate(0)


def _load_locked(stream, path):
    stream.seek(0)
    raw = stream.read()
    stat = os.fstat(stream.fileno())
    signature = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    cached = _CACHE.get(path)
    if cached and cached["signature"] == signature:
        return cached["projection"]
    projection = _projection(_decode_complete_lines(raw, False))
    _CACHE[path] = {"signature": signature, "projection": projection}
    return projection


def append(kind, payload, conversation="", idempotency_key=None):
    """Append one event, or return the existing identity for a replay.

    An idempotency key is namespaced by event kind and deterministically maps to
    one event id.  Physical duplicate events are therefore never appended.
    """
    path = _path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    event_id = (
        _stable_event_id(kind, idempotency_key)
        if idempotency_key is not None else uuid.uuid4().hex
    )
    payload_digest = digest(payload)
    with _LOCK:
        with open(path, "a+b") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                _repair_truncated_tail(stream)
                projection = _load_locked(stream, path)
                if event_id in projection["event_ids"]:
                    if projection["event_digests"][event_id] != payload_digest:
                        raise EventLogError(
                            "idempotency key reused with different payload")
                    return {"status": "duplicate", "id": event_id}
                event = {
                    "version": SCHEMA_VERSION,
                    "index": projection["last_index"] + 1,
                    "id": event_id,
                    "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "kind": str(kind),
                    "conversation": str(conversation or ""),
                    "payload_digest": payload_digest,
                    "payload": payload,
                }
                stream.seek(0, os.SEEK_END)
                stream.write(canonical_bytes(event) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
                updated = _extend_projection(projection, event)
                stat = os.fstat(stream.fileno())
                _CACHE[path] = {
                    "signature": (
                        stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns
                    ),
                    "projection": updated,
                }
                return {
                    "status": "appended",
                    "id": event_id,
                    "index": event["index"],
                }
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def record_input(source_key, conversation, content, metadata=None):
    payload = {
        "source_key": str(source_key),
        "content": str(content or ""),
        "metadata": dict(metadata or {}),
    }
    return append(
        "input.accepted", payload, conversation,
        idempotency_key="input:" + str(source_key),
    )


def record_effect(effect_key, conversation, content, receipt=None):
    payload = {
        "effect_key": str(effect_key),
        "content": str(content or ""),
        "receipt": dict(receipt or {}),
    }
    return append(
        "effect.committed", payload, conversation,
        idempotency_key="effect:" + str(effect_key),
    )


def record_working_set(state):
    state = dict(state or {})
    stable = {key: value for key, value in state.items() if key != "saved_at"}
    current = latest_working_set()
    current_stable = {
        key: value for key, value in current.items() if key != "saved_at"
    }
    if current_stable == stable:
        return {"status": "duplicate", "id": "working-set-unchanged"}
    # Returning to an earlier capsule is a real transition, so working-state
    # events are not globally keyed by content.  Only consecutive equality is
    # collapsed.
    return append(
        "working_set.saved",
        {"state": stable, "saved_at": state.get("saved_at")},
    )


def latest_working_set(path=None):
    return dict(project(path)["working_set"])
