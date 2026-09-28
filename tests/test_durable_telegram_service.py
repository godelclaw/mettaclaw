#!/usr/bin/env python3
"""End to end: the real CeTTa channel service owns a local Bot API.

This process plays the agent. Its unmodified Telegram module reads the
service's deliveries into ordinary activity and sends, deletes and reports
through it. No real Telegram, model provider or live state is involved.

Environment: CETTA_CHANNEL_ROOT (a CeTTa checkout with telegram-channel/1)
and CETTA_SERVICE_BIN (its core Telegram service binary).
"""
import json
import os
import pathlib
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
sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(CETTA / "tests")]
sys.argv[1:] = [SERVICE]  # the shared Bot API fixture reads its binary argument

from test_telegram_transport import TOKEN, Peer, peer  # noqa: E402

import durable_telegram  # noqa: E402
from channels import telegram  # noqa: E402


class BotAPI(Peer):
    def __init__(self, *args):
        self.updates, self.sent, self.deleted, self.message = [], [], [], 500
        super().__init__(*args)

    def add(self, update, chat, sender, text):
        with self.lock:
            self.updates.append({"update_id": update, "message": {"message_id": update,
                "date": 1790000000, "chat": {"id": chat, "type": "private"},
                "from": {"id": sender, "first_name": "Synthetic"}, "text": text}})

    def receipt(self, connection, method, path, body):
        data = json.loads(body)
        name = path.rsplit("/", 1)[-1]
        if name == "getUpdates":
            with self.lock:
                updates = [u for u in self.updates if u["update_id"] >= data["offset"]]
            return 200, [], json.dumps({"ok": True, "result": updates}).encode()
        with self.lock:
            if name == "deleteMessage":
                self.deleted.append((data["chat_id"], data["message_id"]))
                return 200, [], b'{"ok":true,"result":true}'
            assert name == "sendMessage", name
            self.sent.append((data["chat_id"], data["text"]))
            self.message += 1
            message = self.message
        if data["text"] == "lost reply":
            return None
        return 200, [], json.dumps({"ok": True, "result": {"message_id": message,
            "chat": {"id": data["chat_id"]}}}).encode()


def wait(predicate, label, seconds=20):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError(label)


with tempfile.TemporaryDirectory(prefix="lila-durable-telegram-") as temp:
    temp = pathlib.Path(temp)
    token = temp / "token"
    token.write_text(TOKEN)
    token.chmod(0o600)
    state = temp / "service"
    state.mkdir(mode=0o700)
    path = temp / "telegram.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    listener.bind(str(path)); listener.listen(16); path.chmod(0o600)
    os.environ.update({
        "METTACLAW_TELEGRAM_HEALTH_PATH": str(temp / "health.json"),
        "METTACLAW_TELEGRAM_SERVICE_TIMEOUT": "20",
    })
    with peer("http/1.1", None, None, BotAPI) as (api, origin):
        args = [SERVICE, "--run", "--root", str(CETTA), "--state-dir", str(state), "--worker", "lila",
                "--chat", "42", "--chat", "84", "--operator", "7", "--program", "channel",
                "--credential-file", str(token), "--mock-origin", origin,
                "--listener-fd", str(listener.fileno())]
        processes = []

        def start():
            p = subprocess.Popen(args, pass_fds=(listener.fileno(),), stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
            processes.append(p)
            return p

        def kill(p):
            p.send_signal(signal.SIGKILL)
            p.communicate(timeout=10)

        service = start()
        tg = telegram
        tg._token = "123:synthetic"  # direct Bot API calls stay unused here
        tg._allowed_chat_ids = {"42", "84"}
        tg._log_path = str(temp / "telegram.jsonl")
        tg._transport = "durable"
        tg._durable = durable_telegram.Channel(str(path), str(temp / "sequence"))
        tg._durable_receipts = durable_telegram.Receipts()
        tg._running = True
        loop = threading.Thread(target=tg._durable_loop, daemon=True)
        loop.start()
        try:
            # Received by the service, then read as ordinary pending activity.
            api.add(71, 42, 7, "hello Lila")
            wait(lambda: tg.pendingActivityCount() == 1, "delivery into pending activity")
            logged = [json.loads(line) for line in (temp / "telegram.jsonl").read_text().splitlines()]
            assert any(r.get("text") == "hello Lila" for r in logged), logged
            # A reply and an unprompted message, each sent once, with receipts.
            reply = tg.send_message("hello Zar", "42")
            assert reply.startswith("sent message 5") and reply.endswith("to chat 42"), reply
            mid = int(reply.split()[2])
            unprompted = tg.send_message("unprompted check-in", "84")
            assert unprompted.endswith("to chat 84"), unprompted
            assert api.sent == [(42, "hello Zar"), (84, "unprompted check-in")], api.sent
            wait(lambda: any(json.loads(line).get("message_id") == mid
                             for line in (temp / "telegram.jsonl").read_text().splitlines()), "own-send log")
            assert tg.delete_message("42", mid) == "deleted message %d from chat 42" % mid
            assert api.deleted == [(42, mid)], api.deleted
            # The service stops: the agent says it does not know, never "sent".
            kill(service)
            os.environ["METTACLAW_TELEGRAM_SERVICE_TIMEOUT"] = "2"
            answer = tg.send_message("while down", "42")
            assert answer == "send status unknown: the Telegram service did not answer", answer
            # Restarted, the service reads what the supervisor's socket queued:
            # the unanswered message is sent exactly once, however often the
            # client retried it, and its late receipt reaches the own-send log.
            service = start()
            os.environ["METTACLAW_TELEGRAM_SERVICE_TIMEOUT"] = "20"
            assert tg.send_message("after restart", "42").endswith("to chat 42")
            wait(lambda: any(json.loads(line).get("text") == "while down"
                             for line in (temp / "telegram.jsonl").read_text().splitlines()), "late receipt")
            assert api.sent.count((42, "while down")) == 1 and api.sent.count((42, "hello Zar")) == 1, api.sent
            # A lost response is uncertain, and holds only its own chat.
            uncertain = tg.send_message("lost reply", "42")
            assert uncertain.startswith("send uncertain"), uncertain
            assert tg.send_message("other chat", "84").endswith("to chat 84")
            api.add(72, 84, 5, "second message")
            wait(lambda: tg.pendingActivityCount() == 2, "delivery after restart")
            print("durable Telegram transport: service deliveries as activity, keyed replies and "
                  "unprompted sends, own-send log and delete, honest unknown while down, restart "
                  "without repetition, held uncertainty passed")
        finally:
            tg._running = False
            loop.join(timeout=5)
            for p in processes:
                if p.poll() is None:
                    p.send_signal(signal.SIGTERM)
                    p.communicate(timeout=10)
            listener.close()
