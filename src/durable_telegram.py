"""Client of a durable CeTTa Telegram channel service (telegram-channel/1).

The service owns the bot's polling and sending. It records every received
update before this client sees it, and every submitted action before it is
sent, so neither survives only in this process. This client reads delivery
and receipt tasks, acknowledges each one after handling it, and submits keyed
action batches.

Protocol: CWP1 over a private Unix seqpacket socket. A packet is b"CWP1",
a code byte, an ID length byte, the ID and a UTF-8 body.
"""
import json
import os
import socket
import threading
import time

NEXT, RESULT, RECEIPT, SUBMIT = 1, 2, 3, 4
IDLE, TASK, STORED, PENDING, UNKNOWN, CONFLICT, INVALID, UNAVAILABLE, LIMIT = range(64, 73)
BODY_MAX = 65536
TEXT_MAX = 4096  # Unicode scalars per message, as the service validates.


class ChannelError(Exception):
    pass


def chunks(text, limit=TEXT_MAX):
    """Split text into Telegram-sized pieces, preferring line boundaries.

    Python strings index Unicode scalars, which is what the limit counts.
    """
    text = str(text)
    pieces = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit + 1)
        if cut <= 0:
            cut = limit
        pieces.append(text[:cut])
        text = text[cut:].lstrip("\n") if text[cut:cut + 1] == "\n" else text[cut:]
    if text:
        pieces.append(text)
    return pieces


class Channel:
    """One client of the channel service. Thread-safe."""

    def __init__(self, path, sequence_path):
        self.path = path
        self.sequence_path = sequence_path
        self._lock = threading.Lock()
        self._last = self._load_sequence()

    def _load_sequence(self):
        try:
            with open(self.sequence_path, encoding="ascii") as f:
                return int(f.read().strip() or 0)
        except (OSError, ValueError):
            return 0

    def _save_sequence(self, value):
        temporary = "%s.tmp.%d" % (self.sequence_path, os.getpid())
        with open(temporary, "w", encoding="ascii") as f:
            f.write("%d\n" % value)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, self.sequence_path)

    def rpc(self, code, name="", body=""):
        encoded_name = name.encode("ascii")
        encoded_body = body.encode("utf-8")
        if len(encoded_name) > 64 or len(encoded_body) > BODY_MAX:
            raise ChannelError("request too large")
        with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as s:
            s.settimeout(5)
            s.connect(self.path)
            s.sendall(b"CWP1" + bytes([code, len(encoded_name)]) + encoded_name + encoded_body)
            reply = s.recv(6 + 64 + BODY_MAX)
        if len(reply) < 6 or reply[:4] != b"CWP1" or 6 + reply[5] > len(reply):
            raise ChannelError("malformed reply")
        n = reply[5]
        return reply[4], reply[6:6 + n].decode("ascii"), reply[6 + n:].decode("utf-8")

    def pending(self, limit=64):
        """Read up to limit pending tasks, oldest first, answering none."""
        tasks, after = [], ""
        while len(tasks) < limit:
            code, task, body = self.rpc(NEXT, after)
            if code == TASK:
                tasks.append((task, body))
                after = task
            elif code == IDLE:
                break
            elif code == UNKNOWN and after:
                # Answered meanwhile by another reader: return what is known;
                # the next read starts from the oldest pending task again.
                break
            else:
                raise ChannelError("next failed: %d" % code)
        return tasks

    def acknowledge(self, task):
        code, _, _ = self.rpc(RESULT, task, "[]")
        if code != STORED:
            raise ChannelError("acknowledgment failed: %d" % code)

    def key(self, chat_id, thread=0):
        """A fresh LANE.SEQUENCE key, strictly increasing across restarts."""
        chat = int(chat_id)
        thread = int(thread)
        if not chat or thread < 0:
            raise ValueError("invalid lane")
        with self._lock:
            sequence = max(self._last + 1, time.time_ns())
            self._save_sequence(sequence)
            self._last = sequence
        return "%d.%d.%020d" % (chat, thread, sequence)

    def submit(self, key, commands, attempts=4):
        """Record one action batch; resending identical bytes is safe."""
        body = json.dumps(commands, ensure_ascii=False, separators=(",", ":"))
        delay = 0.2
        for _ in range(attempts):
            try:
                code, _, _ = self.rpc(SUBMIT, key, body)
            except OSError:
                code = UNAVAILABLE
            if code == STORED:
                return
            if code not in (UNAVAILABLE, LIMIT):
                raise ChannelError("submission refused: %d" % code)
            time.sleep(delay)
            delay = min(delay * 2, 2.0)
        raise ChannelError("service unavailable")


class Receipts:
    """Delivery receipts by submission key, awaited by the submitting thread."""

    def __init__(self):
        self._results = {}
        self._condition = threading.Condition()

    def record(self, key, position, result):
        with self._condition:
            self._results.setdefault(key, {})[int(position)] = result
            self._condition.notify_all()

    def wait(self, key, count, timeout):
        """Results for positions 0..count-1, or None for those still pending."""
        deadline = time.monotonic() + timeout
        with self._condition:
            while True:
                have = self._results.get(key, {})
                done = [p for p in range(count) if p in have]
                rejected = have.get(-1)
                if rejected is not None or len(done) == count:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            have = self._results.pop(key, {})
            if have.get(-1) is not None:
                return have[-1]
            return [have.get(p) for p in range(count)]


def parse(observation):
    """Classify one task observation from the channel service."""
    value = json.loads(observation)
    if not isinstance(value, list) or not value or not isinstance(value[0], str):
        raise ChannelError("malformed observation")
    return value
