"""Transactional Telegram turn journal shared by both agent adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import threading
import uuid

from services.durable_log import (
    DurableLogConfigurationMismatch,
    DurableLogCorruption,
    HashChainLog,
    canonical_json,
    fingerprint,
)


SCHEMA = "cettaclaw-turn-journal-v1"
FINGERPRINT_FIELD = "policy_fingerprint"
PRIVACY_CLASS = "private-message-content"
TURN_POLICY = {
    "receipt": "journal-before-offset",
    "send_recovery": "drop-in-doubt",
    "send_visibility_invariant": "no-duplicate-human-visible-reply",
    "turn_id": "bot-id:update-id",
}


class TurnJournalError(RuntimeError):
    pass


class TurnJournalCorruption(TurnJournalError):
    pass


class InvalidTransition(TurnJournalError):
    pass


@dataclass(frozen=True)
class Decision:
    kind: str
    turn_id: str | None = None
    send_key: str | None = None


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def make_turn_id(bot_id, update_id):
    return f"{bot_id}:{update_id}"


def _digest(value):
    return "sha256:" + hashlib.sha256(
        canonical_json(value).encode("utf-8")
    ).hexdigest()


def _send_key(turn_id, index, intent):
    return _digest(
        {"turn_id": turn_id, "intent_index": index, "intent": intent}
    )


class TurnJournal:
    def __init__(
        self,
        path,
        *,
        fsync=True,
        clock=_utc_now,
        uuid_factory=uuid.uuid4,
    ):
        self.path = path
        self.clock = clock
        self._lock = threading.RLock()
        try:
            self._chain = HashChainLog(
                path,
                schema=SCHEMA,
                fingerprint_field=FINGERPRINT_FIELD,
                expected_fingerprint=fingerprint(TURN_POLICY),
                generation_payload={
                    "policy": TURN_POLICY,
                    "privacy_class": PRIVACY_CLASS,
                },
                fsync=fsync,
                clock=clock,
                uuid_factory=uuid_factory,
            )
        except (DurableLogCorruption, DurableLogConfigurationMismatch) as exc:
            raise TurnJournalCorruption(str(exc)) from exc
        self.turns = {}
        self.sends = {}
        for event in self._chain.events()[1:]:
            self._apply(event)

    def _turn(self, turn_id):
        turn = self.turns.get(turn_id)
        if turn is None:
            raise InvalidTransition(f"turn not received: {turn_id}")
        return turn

    def _apply(self, event):
        event_type = event.get("event_type")
        turn_id = event.get("turn_id")
        if event_type == "Received":
            if turn_id in self.turns:
                raise TurnJournalCorruption("duplicate Received event")
            self.turns[turn_id] = {
                "update_digest": event.get("update_digest"),
                "offset": None,
                "intents": None,
                "done": False,
            }
            return

        turn = self.turns.get(turn_id)
        if turn is None:
            raise TurnJournalCorruption(
                f"{event_type} precedes Received"
            )
        if event_type == "OffsetCommitted":
            if turn["offset"] is not None:
                raise TurnJournalCorruption("duplicate OffsetCommitted event")
            turn["offset"] = str(event.get("offset"))
        elif event_type == "ActionsCommitted":
            if turn["offset"] is None or turn["intents"] is not None:
                raise TurnJournalCorruption(
                    "ActionsCommitted has an invalid predecessor"
                )
            intents = tuple(event.get("intents") or ())
            turn["intents"] = intents
            for intent in intents:
                send_key = intent.get("send_key")
                if not isinstance(send_key, str) or send_key in self.sends:
                    raise TurnJournalCorruption("invalid or duplicate send_key")
                self.sends[send_key] = {
                    "turn_id": turn_id,
                    "status": "Pending",
                }
        elif event_type == "Sending":
            send = self.sends.get(event.get("send_key"))
            if send is None or send["turn_id"] != turn_id:
                raise TurnJournalCorruption("Sending lacks committed intent")
            if send["status"] != "Pending":
                raise TurnJournalCorruption("duplicate Sending transition")
            send["status"] = "Sending"
        elif event_type == "Sent":
            send = self.sends.get(event.get("send_key"))
            if send is None or send["turn_id"] != turn_id:
                raise TurnJournalCorruption("Sent lacks committed intent")
            if send["status"] != "Sending":
                raise TurnJournalCorruption("Sent does not follow Sending")
            send["status"] = "Sent"
            send["message_id"] = str(event.get("message_id"))
        elif event_type == "SendDroppedInDoubt":
            send = self.sends.get(event.get("send_key"))
            if send is None or send["turn_id"] != turn_id:
                raise TurnJournalCorruption(
                    "SendDroppedInDoubt lacks committed intent"
                )
            if send["status"] != "Sending":
                raise TurnJournalCorruption(
                    "SendDroppedInDoubt does not follow Sending"
                )
            send["status"] = "DroppedInDoubt"
        elif event_type == "TurnDone":
            if turn["done"] or turn["intents"] is None:
                raise TurnJournalCorruption("invalid TurnDone transition")
            if any(
                self.sends[intent["send_key"]]["status"]
                not in {"Sent", "DroppedInDoubt"}
                for intent in turn["intents"]
            ):
                raise TurnJournalCorruption(
                    "TurnDone precedes send resolution"
                )
            turn["done"] = True
        else:
            raise TurnJournalCorruption(
                f"unsupported turn event: {event_type}"
            )

    def _append(self, payload):
        event = self._chain.append(
            {"recorded_at": self.clock(), **dict(payload)}
        )
        self._apply(event)
        return event

    def record_received(self, bot_id, update_id, update):
        if not isinstance(update, dict):
            raise ValueError("update must be a JSON object")
        turn_id = make_turn_id(bot_id, update_id)
        update_digest = _digest(update)
        with self._lock:
            existing = self.turns.get(turn_id)
            if existing is not None:
                if existing["update_digest"] != update_digest:
                    raise InvalidTransition(
                        "same turn_id has different update content"
                    )
                return Decision("AlreadyReceived", turn_id)
            self._append(
                {
                    "event_type": "Received",
                    "turn_id": turn_id,
                    "bot_id": str(bot_id),
                    "update_id": str(update_id),
                    "update_digest": update_digest,
                    "update": update,
                }
            )
            return Decision("ReceivedDurable", turn_id)

    def record_offset_committed(self, turn_id, offset):
        offset = str(offset)
        with self._lock:
            turn = self._turn(turn_id)
            if turn["offset"] is not None:
                if turn["offset"] != offset:
                    raise InvalidTransition(
                        "turn already committed a different offset"
                    )
                return Decision("OffsetAlreadyCommitted", turn_id)
            self._append(
                {
                    "event_type": "OffsetCommitted",
                    "turn_id": turn_id,
                    "offset": offset,
                }
            )
            return Decision("OffsetCommitted", turn_id)

    def record_actions_committed(self, turn_id, intents):
        normalized = []
        for index, intent in enumerate(intents):
            if not isinstance(intent, dict):
                raise ValueError("each outbound intent must be an object")
            intent = dict(intent)
            if not isinstance(intent.get("kind"), str):
                raise ValueError("each outbound intent needs a kind")
            normalized.append(
                {
                    **intent,
                    "send_key": _send_key(turn_id, index, intent),
                }
            )
        normalized = tuple(normalized)
        with self._lock:
            turn = self._turn(turn_id)
            if turn["offset"] is None:
                raise InvalidTransition(
                    "offset must commit before actions"
                )
            if turn["intents"] is not None:
                if tuple(turn["intents"]) != normalized:
                    raise InvalidTransition(
                        "turn already committed different actions"
                    )
                return tuple(
                    intent["send_key"] for intent in turn["intents"]
                )
            self._append(
                {
                    "event_type": "ActionsCommitted",
                    "turn_id": turn_id,
                    "intents": list(normalized),
                }
            )
            return tuple(intent["send_key"] for intent in normalized)

    def prepare_send(self, send_key):
        with self._lock:
            send = self.sends.get(send_key)
            if send is None:
                raise InvalidTransition("unknown send_key")
            turn_id = send["turn_id"]
            if send["status"] == "Pending":
                self._append(
                    {
                        "event_type": "Sending",
                        "turn_id": turn_id,
                        "send_key": send_key,
                    }
                )
                return Decision("SendPrepared", turn_id, send_key)
            if send["status"] == "Sending":
                self._append(
                    {
                        "event_type": "SendDroppedInDoubt",
                        "turn_id": turn_id,
                        "send_key": send_key,
                        "reason": "ambiguous-after-recovery",
                    }
                )
                return Decision("DropInDoubt", turn_id, send_key)
            if send["status"] == "Sent":
                return Decision("AlreadySent", turn_id, send_key)
            return Decision("AlreadyDropped", turn_id, send_key)

    def record_sent(self, send_key, message_id):
        with self._lock:
            send = self.sends.get(send_key)
            if send is None or send["status"] != "Sending":
                raise InvalidTransition(
                    "Sent must immediately follow Sending"
                )
            self._append(
                {
                    "event_type": "Sent",
                    "turn_id": send["turn_id"],
                    "send_key": send_key,
                    "message_id": str(message_id),
                }
            )
            return Decision("SentRecorded", send["turn_id"], send_key)

    def recover_in_doubt(self):
        with self._lock:
            keys = tuple(
                key
                for key, send in self.sends.items()
                if send["status"] == "Sending"
            )
            for send_key in keys:
                send = self.sends[send_key]
                self._append(
                    {
                        "event_type": "SendDroppedInDoubt",
                        "turn_id": send["turn_id"],
                        "send_key": send_key,
                        "reason": "ambiguous-after-recovery",
                    }
                )
            return keys

    def mark_turn_done(self, turn_id):
        with self._lock:
            turn = self._turn(turn_id)
            if turn["done"]:
                return Decision("AlreadyDone", turn_id)
            if turn["intents"] is None:
                raise InvalidTransition("actions are not committed")
            unresolved = [
                intent["send_key"]
                for intent in turn["intents"]
                if self.sends[intent["send_key"]]["status"]
                not in {"Sent", "DroppedInDoubt"}
            ]
            if unresolved:
                raise InvalidTransition("outbound sends remain unresolved")
            self._append(
                {"event_type": "TurnDone", "turn_id": turn_id}
            )
            return Decision("TurnDone", turn_id)

    def snapshot(self):
        return {
            "turns": len(self.turns),
            "done_turns": sum(turn["done"] for turn in self.turns.values()),
            "sends": len(self.sends),
            "send_states": {
                state: sum(
                    send["status"] == state for send in self.sends.values()
                )
                for state in (
                    "Pending",
                    "Sending",
                    "Sent",
                    "DroppedInDoubt",
                )
            },
        }
