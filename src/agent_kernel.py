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
_PROCESS_EPISODE = uuid.uuid4().hex


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
        "invocations": {},
        "receipts": {},
        "effects": set(),
        "effect_attempts": {},
        "effect_observations": {},
        "working_set": {},
        "latest_turn": {},
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
        elif kind == "controller.invoked":
            result["invocations"][event["id"]] = dict(event["payload"])
        elif kind == "decision.issued":
            result["receipts"][event["id"]] = dict(event["payload"])
        elif kind in ("effect.attempted", "effect.committed"):
            key = event["payload"].get("effect_key")
            if key:
                result["effects"].add(str(key))
                if kind == "effect.attempted":
                    result["effect_attempts"][str(key)] = dict(event["payload"])
        elif kind == "effect.observed":
            key = event["payload"].get("effect_key")
            if key:
                result["effect_observations"][str(key)] = dict(event["payload"])
        elif kind == "working_set.saved":
            state = event["payload"].get("state")
            if isinstance(state, dict):
                result["working_set"] = dict(state)
                saved_at = event["payload"].get("saved_at")
                if isinstance(saved_at, (int, float)):
                    result["working_set"]["saved_at"] = saved_at
        elif kind == "turn.began":
            result["latest_turn"] = dict(event["payload"])
            result["latest_turn"].update({
                "began_event": event["id"],
                "completed": False,
            })
        elif kind == "turn.completed":
            payload = event["payload"]
            latest = result["latest_turn"]
            if (latest.get("episode") == payload.get("episode")
                    and latest.get("turn") == payload.get("turn")):
                latest.update({
                    "completed": True,
                    "completed_event": event["id"],
                    "outcome": payload.get("outcome", ""),
                    "receipt_id": payload.get("receipt_id", ""),
                    "observation_digest": payload.get(
                        "observation_digest", ""),
                    "had_errors": bool(payload.get("had_errors", False)),
                })
    return result


def _extend_projection(projection, event):
    updated = {
        "count": projection["count"] + 1,
        "last_index": event["index"],
        "event_ids": set(projection["event_ids"]),
        "event_digests": dict(projection["event_digests"]),
        "frontier": dict(projection["frontier"]),
        "invocations": dict(projection["invocations"]),
        "receipts": dict(projection["receipts"]),
        "effects": set(projection["effects"]),
        "effect_attempts": dict(projection["effect_attempts"]),
        "effect_observations": dict(projection["effect_observations"]),
        "working_set": dict(projection["working_set"]),
        "latest_turn": dict(projection["latest_turn"]),
    }
    updated["event_ids"].add(event["id"])
    updated["event_digests"][event["id"]] = event["payload_digest"]
    kind = event["kind"]
    conversation = event.get("conversation", "")
    if kind == "input.accepted" and conversation:
        updated["frontier"][conversation] = event["id"]
    elif kind == "controller.invoked":
        updated["invocations"][event["id"]] = dict(event["payload"])
    elif kind == "decision.issued":
        updated["receipts"][event["id"]] = dict(event["payload"])
    elif kind in ("effect.attempted", "effect.committed"):
        key = event["payload"].get("effect_key")
        if key:
            updated["effects"].add(str(key))
            if kind == "effect.attempted":
                updated["effect_attempts"][str(key)] = dict(event["payload"])
    elif kind == "effect.observed":
        key = event["payload"].get("effect_key")
        if key:
            updated["effect_observations"][str(key)] = dict(event["payload"])
    elif kind == "working_set.saved":
        state = event["payload"].get("state")
        if isinstance(state, dict):
            updated["working_set"] = dict(state)
            saved_at = event["payload"].get("saved_at")
            if isinstance(saved_at, (int, float)):
                updated["working_set"]["saved_at"] = saved_at
    elif kind == "turn.began":
        updated["latest_turn"] = dict(event["payload"])
        updated["latest_turn"].update({
            "began_event": event["id"],
            "completed": False,
        })
    elif kind == "turn.completed":
        payload = event["payload"]
        latest = updated["latest_turn"]
        if (latest.get("episode") == payload.get("episode")
                and latest.get("turn") == payload.get("turn")):
            latest.update({
                "completed": True,
                "completed_event": event["id"],
                "outcome": payload.get("outcome", ""),
                "receipt_id": payload.get("receipt_id", ""),
                "observation_digest": payload.get(
                    "observation_digest", ""),
                "had_errors": bool(payload.get("had_errors", False)),
            })
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


def current_frontier(conversation):
    return str(project()["frontier"].get(str(conversation), ""))


def _frontier_map(value, conversation):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as exc:
            raise EventLogError("invocation frontiers are not valid JSON") from exc
    if value is None:
        value = {str(conversation): current_frontier(conversation)}
    if not isinstance(value, dict):
        raise EventLogError("invocation frontiers are not a mapping")
    return {
        str(key): str(frontier)
        for key, frontier in sorted(value.items())
        if str(key)
    }


def latest_invocation_frontiers():
    """Last context frontier, for a restart before the next batch drain."""
    invocations = project()["invocations"]
    if not invocations:
        return {}
    latest = next(reversed(invocations.values()))
    return dict(latest.get("frontiers") or {})


def begin_invocation(conversation, context, controller_revision,
                     frontiers=None):
    """Bind the request to causal inputs consumed while assembling context."""
    conversation = str(conversation or "")
    request = {
        "conversation": conversation,
        "frontiers": _frontier_map(frontiers, conversation),
        "context_digest": digest(str(context or "")),
        "controller_revision": str(controller_revision or ""),
    }
    identity = digest(request)
    result = append(
        "controller.invoked", request, conversation,
        idempotency_key="invocation:" + identity,
    )
    return result["id"]


def issue_decision(invocation_id, proposal):
    """Bind a proposal to the immutable request supplied to its invocation."""
    projection = project()
    invocation = projection["invocations"].get(str(invocation_id))
    if not invocation:
        raise EventLogError("decision refers to an unissued invocation")
    receipt = dict(invocation)
    receipt.update({
        "invocation_id": str(invocation_id),
        "proposal_digest": digest(str(proposal or "")),
    })
    identity = digest(receipt)
    result = append(
        "decision.issued", receipt, invocation.get("conversation", ""),
        idempotency_key="decision:" + identity,
    )
    return result["id"]


def receipt_current(receipt_id, controller_revision=""):
    """Whether an issued receipt still names the current causal frontier."""
    projection = project()
    receipt = projection["receipts"].get(str(receipt_id))
    if not receipt:
        return 0
    for conversation, frontier in (receipt.get("frontiers") or {}).items():
        if projection["frontier"].get(conversation, "") != frontier:
            return 0
    revision = str(controller_revision or "")
    if revision and revision != receipt.get("controller_revision", ""):
        return 0
    return 1


def _semantic_effect_key(receipt, effect_type, target, content):
    # Proposal serialization is deliberately absent: different plans that
    # encode the same externally visible effect must share one semantic key.
    return digest({
        "conversation": receipt.get("conversation", ""),
        "frontiers": receipt.get("frontiers", {}),
        "effect_type": str(effect_type),
        "target": str(target),
        "content": str(content),
    })


def prepare_effect(receipt_id, controller_revision, effect_type, target,
                   content):
    """Commit one durable at-most-once attempt before crossing the network."""
    with _LOCK:
        projection = project()
        receipt = projection["receipts"].get(str(receipt_id))
        if not receipt or not receipt_current(receipt_id, controller_revision):
            return {"status": "stale"}
        effect_key = _semantic_effect_key(
            receipt, effect_type, target, content)
        if effect_key in projection["effects"]:
            return {"status": "duplicate", "effect_key": effect_key}
        result = append(
            "effect.attempted",
            {
                "effect_key": effect_key,
                "receipt_id": str(receipt_id),
                "effect_type": str(effect_type),
                "target": str(target),
                "content_digest": digest(str(content)),
            },
            receipt.get("conversation", ""),
            idempotency_key="effect-attempt:" + effect_key,
        )
        return {
            "status": result["status"],
            "effect_key": effect_key,
        }


def observe_effect(effect_key, status, receipt=None):
    payload = {
        "effect_key": str(effect_key),
        "status": str(status),
        "receipt": dict(receipt or {}),
    }
    return append(
        "effect.observed", payload,
        idempotency_key="effect-observation:" + str(effect_key),
    )


def _truthy(value):
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def begin_turn(turn, source, has_prior_receipt=False, frontiers=None):
    """Record the minimal facts from which the current attention view derives."""
    payload = {
        "episode": _PROCESS_EPISODE,
        "turn": str(turn),
        "source": str(source),
        "has_prior_receipt": _truthy(has_prior_receipt),
        "frontiers": _frontier_map(frontiers, ""),
    }
    result = append(
        "turn.began", payload,
        idempotency_key="turn-began:%s:%s" % (_PROCESS_EPISODE, turn),
    )
    return 1 if result["status"] in ("appended", "duplicate") else 0


def complete_turn(turn, outcome, receipt_id="", observation="",
                  had_errors=False):
    """Record completion without creating a second mutable attention store."""
    payload = {
        "episode": _PROCESS_EPISODE,
        "turn": str(turn),
        "outcome": str(outcome),
        "receipt_id": str(receipt_id or ""),
        "observation_digest": digest(str(observation or "")),
        "had_errors": _truthy(had_errors),
    }
    result = append(
        "turn.completed", payload,
        idempotency_key="turn-completed:%s:%s" % (_PROCESS_EPISODE, turn),
    )
    return 1 if result["status"] in ("appended", "duplicate") else 0


def stuck_status(path=None):
    """Derive narrow syntactic non-progress signals from completed turns.

    This detector observes repetition only. It does not decide that a hard
    problem should be abandoned or that repeated work lacks semantic value.
    """
    projection = project(path)
    samples = []
    for event in read_events(path):
        if event.get("kind") != "turn.completed":
            continue
        payload = event.get("payload") or {}
        receipt = projection["receipts"].get(
            str(payload.get("receipt_id", "")), {})
        signature = (
            str(receipt.get("proposal_digest", "")),
            str(payload.get("observation_digest", "")),
            str(payload.get("outcome", "")),
        )
        samples.append({
            "signature": signature,
            "had_errors": bool(payload.get("had_errors", False)),
        })
    if len(samples) >= 3:
        tail = samples[-3:]
        if (all(sample["had_errors"] for sample in tail)
                and len({sample["signature"] for sample in tail}) == 1):
            return {"suspicious": True, "kind": "repeated-error", "count": 3}
    if len(samples) >= 4:
        tail = samples[-4:]
        if len({sample["signature"] for sample in tail}) == 1:
            return {"suspicious": True, "kind": "repeated-action", "count": 4}
    if len(samples) >= 6:
        signatures = [sample["signature"] for sample in samples[-6:]]
        if (signatures[0] != signatures[1]
                and signatures[0::2] == [signatures[0]] * 3
                and signatures[1::2] == [signatures[1]] * 3):
            return {"suspicious": True, "kind": "ping-pong", "count": 6}
    return {"suspicious": False, "kind": "clear", "count": len(samples)}


def stuck_view():
    status = stuck_status()
    if not status["suspicious"]:
        return "clear (syntactic signal only)"
    return "suspicious:%s:%d (syntactic signal only)" % (
        status["kind"], status["count"])


def _sexpr_string(value):
    return json.dumps(str(value), ensure_ascii=False)


def attention_view_text():
    """Project the latest turn into the existing MeTTa S-expression view."""
    projection = project()
    turn = projection["latest_turn"]
    if not turn:
        return "()"
    label = _sexpr_string(turn.get("turn", ""))
    source = _sexpr_string(turn.get("source", ""))
    frontiers = turn.get("frontiers") or {}
    fresh = all(
        projection["frontier"].get(str(conversation), "") == str(frontier)
        for conversation, frontier in frontiers.items()
    )
    truth = "True" if fresh else "False"
    atoms = [
        "(node (event %s) event %s)" % (label, source),
        "(node (task %s) task respond-to-foreground)" % label,
        "(edge (event %s) foreground-of (task %s))" % (label, label),
        "(frontier-fresh %s)" % truth,
        "(pending-input %s)" % ("False" if fresh else "True"),
    ]
    if turn.get("has_prior_receipt"):
        atoms.extend([
            "(node prior-receipt receipt)",
            "(edge prior-receipt evidence-for (task %s))" % label,
        ])
    if turn.get("completed"):
        receipt_id = str(turn.get("receipt_id", ""))
        receipt = projection["receipts"].get(receipt_id, {})
        proposal = _sexpr_string(receipt.get("proposal_digest", ""))
        outcome = _sexpr_string(turn.get("outcome", ""))
        receipt_label = _sexpr_string(receipt_id)
        atoms.extend([
            "(node (proposal %s) proposal %s)" % (label, proposal),
            "(edge (task %s) proposes (proposal %s))" % (label, label),
            "(node (receipt %s) receipt %s %s)" % (
                label, receipt_label, outcome),
            "(edge (proposal %s) observed-as (receipt %s))" % (
                label, label),
        ])
    return "(" + " ".join(atoms) + ")"


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
