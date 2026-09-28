#!/usr/bin/env python3
"""Chaos soak: the CeTTa channel service killed repeatedly under traffic.

Random updates arrive and a client sends to three chats while the service is
SIGKILLed and restarted every few seconds. One chat loses a response once;
its lane holds until an operator releases it through the control socket.
A SIGKILL during a send
also makes that send uncertain. An operator releases every uncertain lane
after a pause. Afterwards: every update was handled exactly once by the
client; in every chat no message was sent twice, sent messages kept their
submission order, and every message ended delivered or explicitly
uncertain; no other chat was ever addressed. No real Telegram, credentials or live state are involved.

Environment: CETTA_CHANNEL_ROOT, CETTA_SERVICE_BIN; SOAK_SECONDS (default 90).
"""
import json
import os
import pathlib
import random
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
CETTA = pathlib.Path(os.environ["CETTA_CHANNEL_ROOT"]).resolve()
SERVICE = str(pathlib.Path(os.environ["CETTA_SERVICE_BIN"]).resolve())
SECONDS = float(os.environ.get("SOAK_SECONDS", "90"))
sys.path[:0] = [str(ROOT / "src"), str(CETTA / "tests")]
sys.argv[1:] = [SERVICE]

from test_telegram_transport import TOKEN, Peer, peer  # noqa: E402

import durable_telegram  # noqa: E402

CLEAN, LOSSY = (42, 84), 126
rng = random.Random(20260929)


class BotAPI(Peer):
    def __init__(self, *args):
        self.updates, self.sent, self.next_update, self.message = [], [], 1, 1000
        super().__init__(*args)

    def inject(self):
        with self.lock:
            update = self.next_update
            self.next_update += 1
            chat = rng.choice(CLEAN + (LOSSY,))
            self.updates.append({"update_id": update, "message": {"message_id": update,
                "chat": {"id": chat, "type": "private"}, "from": {"id": 5}, "text": "u%d" % update}})
            return update

    def receipt(self, connection, method, path, body):
        data = json.loads(body)
        if path.endswith("/getUpdates"):
            with self.lock:
                updates = [u for u in self.updates if u["update_id"] >= data["offset"]][:100]
            time.sleep(rng.random() * 0.02)
            return 200, [], json.dumps({"ok": True, "result": updates}).encode()
        with self.lock:
            self.sent.append((data["chat_id"], data["text"]))
            self.message += 1
            message = self.message
        if data["text"].endswith(":LOST"):
            return None
        time.sleep(rng.random() * 0.05)
        return 200, [], json.dumps({"ok": True, "result": {"message_id": message,
            "chat": {"id": data["chat_id"]}}}).encode()


with tempfile.TemporaryDirectory(prefix="lila-durable-soak-") as temp:
    temp = pathlib.Path(temp)
    token = temp / "token"; token.write_text(TOKEN); token.chmod(0o600)
    state = temp / "service"; state.mkdir(mode=0o700)
    path = temp / "client.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    listener.bind(str(path)); listener.listen(64); path.chmod(0o600)
    control_path = temp / "operator.sock"
    control = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    control.bind(str(control_path)); control.listen(8); control_path.chmod(0o600)
    with peer("http/1.1", None, None, BotAPI) as (api, origin):
        args = [SERVICE, "--run", "--root", str(CETTA), "--state-dir", str(state), "--worker", "lila",
                "--chat", "42", "--chat", "84", "--chat", str(LOSSY), "--program", "channel",
                "--credential-file", str(token), "--mock-origin", origin,
                "--listener-fd", str(listener.fileno()), "--operator-fd", str(control.fileno())]
        current = {"proc": None}
        kills = [0]

        def start():
            current["proc"] = subprocess.Popen(args, pass_fds=(listener.fileno(), control.fileno()),
                                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)

        start()
        channel = durable_telegram.Channel(str(path), str(temp / "sequence"))
        outbox = durable_telegram.Outbox(channel, str(temp / "outbox"))
        running = threading.Event(); running.set()
        handled, receipts, lock = {}, {}, threading.Lock()
        submitted = {chat: [] for chat in CLEAN + (LOSSY,)}
        uncertain, released = [], []

        def ctc(*words):
            with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as s:
                s.settimeout(5); s.connect(str(control_path))
                s.sendall(b"CTC1" + " ".join(words).encode())
                return s.recv(256)[4:].decode()

        def operator():
            # Each held lane gets an operator decision after a pause.
            done = 0
            while running.is_set() or time.monotonic() < quiesce_until[0]:
                with lock:
                    todo = uncertain[done:]
                for key in todo:
                    time.sleep(1)
                    request = "operator-%d" % done
                    while key not in released and (running.is_set() or time.monotonic() < quiesce_until[0]):
                        try:
                            ctc("release", request, durable_telegram.lane_of(key), key)
                        except OSError:
                            pass
                        time.sleep(0.5)
                    done += 1
                time.sleep(0.1)

        def reader():
            seen = set()
            while running.is_set() or time.monotonic() < quiesce_until[0]:
                try:
                    tasks = channel.pending(64)
                    for task, observation in tasks:
                        if task not in seen:
                            value = json.loads(observation)
                            with lock:
                                if value[0] == "input":
                                    update = value[4]["update_id"]
                                    handled[update] = handled.get(update, 0) + 1
                                elif value[0] == "delivery":
                                    receipts.setdefault(value[1], []).append(value[4])
                                    if value[4][0] == "uncertain":
                                        outbox.hold(durable_telegram.lane_of(value[1]))
                                        uncertain.append(value[1])
                                elif value[0] == "released":
                                    outbox.release(value[1])
                                    released.append(value[2])
                            seen.add(task)
                        channel.acknowledge(task)
                    if not tasks:
                        time.sleep(0.05)
                except (OSError, durable_telegram.ChannelError):
                    time.sleep(0.2)

        def sender(chat):
            n, lost = 0, False
            while running.is_set():
                n += 1
                text = "%d:%d" % (chat, n)
                if chat == LOSSY and not lost and n == 5:
                    text, lost = "%d:LOST" % chat, True
                key = channel.key(chat)
                outbox.enqueue(key, [["send", text, "plain"]])
                outcome = "stored" if outbox.wait_stored(key, 2) is True else "queued"
                submitted[chat].append((key, text, outcome))
                time.sleep(0.1 + rng.random() * 0.4)

        def chaos():
            while running.is_set():
                time.sleep(3 + rng.random() * 5)
                if not running.is_set():
                    break
                current["proc"].send_signal(signal.SIGKILL)
                current["proc"].communicate(timeout=10)
                kills[0] += 1
                time.sleep(rng.random() * 1.5)
                start()

        def traffic():
            while running.is_set():
                api.inject()
                time.sleep(0.05 + rng.random() * 0.3)

        quiesce_until = [0.0]
        threads = [threading.Thread(target=f, daemon=True) for f in (reader, chaos, traffic, operator)]
        threads += [threading.Thread(target=sender, args=(c,), daemon=True) for c in CLEAN + (LOSSY,)]
        for t in threads:
            t.start()
        time.sleep(SECONDS)
        quiesce_until[0] = time.monotonic() + 30
        running.clear()
        for t in threads[1:4] + threads[5:]:
            t.join(timeout=30)
        # Quiesce: the last service instance drains queued work, then the reader stops.
        injected = api.next_update - 1
        until = time.monotonic() + 30
        while time.monotonic() < until:
            with lock:
                done_inputs = len(handled) == injected
                all_done = all(key in receipts for c in CLEAN + (LOSSY,) for key, _, _ in submitted[c])
            if done_inputs and all_done:
                break
            time.sleep(0.2)
        quiesce_until[0] = 0
        threads[0].join(timeout=10)
        threads[4].join(timeout=10)
        alive = current["proc"].poll() is None
        if not alive:
            print("SERVICE EXITED", current["proc"].returncode, current["proc"].stderr.read()[-3000:], file=sys.stderr)
        rss = 0
        try:
            with open("/proc/%d/status" % current["proc"].pid) as f:
                rss = next(int(line.split()[1]) for line in f if line.startswith("VmRSS"))
        except (OSError, StopIteration):
            pass
        current["proc"].send_signal(signal.SIGTERM)
        _, err = current["proc"].communicate(timeout=15)
        if err:
            print("SERVICE STDERR:", err[-3000:], file=sys.stderr)
        import sqlite3
        with sqlite3.connect("file:%s?mode=ro" % (state / "journal.db"), uri=True) as db:
            counts = dict(db.execute("SELECT space, count(*) FROM records GROUP BY space"))
        print("JOURNAL SPACES:", counts, file=sys.stderr)
        assert TOKEN.split(":")[1] not in (err or "")
        journal = sum(p.stat().st_size for p in state.iterdir())
        listener.close()
        control.close()

    # Every update handled exactly once by the client.
    assert sorted(handled) == list(range(1, injected + 1)), (injected, len(handled))
    assert all(count == 1 for count in handled.values()), [u for u, c in handled.items() if c > 1]
    # Every chat: at most once, in order, every message resolved.
    outcome = {}
    for key, values in receipts.items():
        outcome[key] = values[0][0]
    for chat in CLEAN + (LOSSY,):
        texts = [text for key, text, _ in submitted[chat]]
        got = [text for c, text in api.sent if c == chat]
        assert len(got) == len(set(got)), ("duplicate", chat)
        order = [t for t in texts if t in set(got)]
        assert got == order, ("order", chat, got[:5], order[:5])
        unresolved = [text for key, text, _ in submitted[chat] if key not in outcome]
        assert not unresolved, ("unresolved", chat, unresolved[:5])
        missing_ok = all(outcome[key] == "uncertain" for key, text, _ in submitted[chat] if text not in got)
        assert missing_ok, ("lost without uncertainty", chat)
        if False:
            first = next(i for i in range(min(len(got), len(texts)) + 1)
                         if i == min(len(got), len(texts)) or got[i] != texts[i])
            dup = sorted({x for x in got if got.count(x) > 1})
            missing = [x for x in texts if x not in got]
            outcomes = {text: o for _, text, o in submitted[chat]}
            raise AssertionError(dict(chat=chat, sent=len(got), submitted=len(texts), first=first,
                around_got=got[first-2:first+3], around_submitted=texts[first-2:first+3],
                duplicates=dup[:10], missing=[(m, outcomes.get(m)) for m in missing[:10]]))
    # The deliberately lost response: received once by the Bot API, uncertain,
    # released; the lane then went on.
    lost_key = next(key for key, text, _ in submitted[LOSSY] if text.endswith(":LOST"))
    assert outcome[lost_key] == "uncertain" and lost_key in released
    assert [t for c, t in api.sent if c == LOSSY].count("%d:LOST" % LOSSY) == 1
    assert sorted(released) == sorted(uncertain), (uncertain, released)
    assert all(c in CLEAN + (LOSSY,) for c, _ in api.sent)
    unknown = sum(o == "queued" for chat in submitted for _, _, o in submitted[chat])
    sent_total = sum(len(submitted[c]) for c in CLEAN + (LOSSY,))
    delivered_total = sum(v == "delivered" for v in outcome.values())
    print("soak %.0fs: %d service kills, %d updates handled once; %d submissions: %d delivered once in order, "
          "%d uncertain and released by the operator, none sent twice or lost silently "
          "(%d queued while the service was down); journal %.1f MB, final RSS %d kB"
          % (SECONDS, kills[0], injected, sent_total, delivered_total, len(uncertain), unknown, journal / 1e6, rss))
