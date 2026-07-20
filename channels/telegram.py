import os
import json
import subprocess
import tempfile
import re
import threading
import time

import requests

_running = False
_thread = None
_token = ""
_allowed_chat_ids = set()
_allow_private_chats = True
_last_chat_id = ""
_reply_chat_id = ""
_last_message_is_human = False
_last_from_bot = False
_pending_messages = []
_offset = None
_offset_path = ""
_log_path = ""
_msg_lock = threading.Lock()
_log_lock = threading.Lock()
_chat_titles = {}  # chat_id -> last-seen display title (for outbound records)


def _api_base():
    return os.environ.get("METTACLAW_TELEGRAM_BASE_URL",
                          "https://api.telegram.org")


def _api(method, token=""):
    return f"{_api_base()}/bot{token or _token}/{method}"


def _split_chat_ids(raw):
    return {part.strip() for part in str(raw or "").split(",") if part.strip()}


def _chat_is_allowed(chat):
    chat_id = str(chat.get("id", ""))
    if _allow_private_chats and chat.get("type") == "private":
        return True
    return chat_id in _allowed_chat_ids


def _compact(value, limit=160):
    value = "" if value is None else str(value)
    value = " ".join(value.replace("\r", " ").replace("\n", " ").split())
    if len(value) > limit:
        return value[: limit - 1] + "…"
    return value


def _field(key, value, limit=160):
    value = _compact(value, limit=limit)
    if not value:
        return None
    return f"{key}={json.dumps(value, ensure_ascii=False)}"


def _bool_field(key, value):
    return f"{key}={'true' if value else 'false'}"


def _display_user(user):
    if not user:
        return ""
    if user.get("username"):
        return "@" + str(user["username"])
    return user.get("first_name") or str(user.get("id", ""))


def _display_chat(chat):
    if not chat:
        return ""
    if chat.get("title"):
        return chat["title"]
    if chat.get("username"):
        return "@" + str(chat["username"])
    return chat.get("first_name") or str(chat.get("id", ""))


def _message_excerpt(message, limit=180):
    if not message:
        return ""
    return _compact(message.get("text") or message.get("caption") or "", limit=limit)


def _forward_fields(message):
    origin = message.get("forward_origin") or {}
    if origin:
        origin_type = origin.get("type", "")
        fields = [_bool_field("forwarded", True), _field("forward_type", origin_type)]
        if origin_type == "user":
            user = origin.get("sender_user") or {}
            fields.extend([
                _field("forward_from", _display_user(user)),
                _field("forward_from_id", user.get("id")),
            ])
        elif origin_type == "hidden_user":
            fields.append(_field("forward_from", origin.get("sender_user_name")))
        elif origin_type in {"chat", "channel"}:
            chat = origin.get("sender_chat") or origin.get("chat") or {}
            fields.extend([
                _field("forward_from_chat", _display_chat(chat)),
                _field("forward_from_chat_id", chat.get("id")),
            ])
        fields.extend([
            _field("forward_message_id", origin.get("message_id")),
            _field("forward_signature", origin.get("author_signature")),
        ])
        return [f for f in fields if f]

    # Older Telegram payloads used these fields before forward_origin.
    legacy_user = message.get("forward_from") or {}
    legacy_chat = message.get("forward_from_chat") or {}
    legacy_name = message.get("forward_sender_name")
    if legacy_user or legacy_chat or legacy_name:
        return [
            _bool_field("forwarded", True),
            _field("forward_from", _display_user(legacy_user) or legacy_name),
            _field("forward_from_id", legacy_user.get("id")),
            _field("forward_from_chat", _display_chat(legacy_chat)),
            _field("forward_from_chat_id", legacy_chat.get("id")),
            _field("forward_signature", message.get("author_signature")),
        ]
    return [_bool_field("forwarded", False)]


def _reply_fields(message):
    reply = message.get("reply_to_message") or {}
    external = message.get("external_reply") or {}
    quote = message.get("quote") or {}
    fields = []
    if reply:
        sender = reply.get("from") or {}
        chat = reply.get("chat") or {}
        fields.extend([
            _bool_field("is_reply", True),
            _field("reply_to_message_id", reply.get("message_id")),
            _field("reply_to_from", _display_user(sender)),
            _field("reply_to_from_id", sender.get("id")),
            _field("reply_to_chat", _display_chat(chat)),
            _field("reply_to_excerpt", _message_excerpt(reply)),
        ])
    else:
        fields.append(_bool_field("is_reply", False))
    if external:
        fields.extend([
            _field("external_reply_origin", external.get("origin")),
            _field("external_reply_excerpt", _message_excerpt(external)),
        ])
    if quote:
        fields.append(_field("quote", quote.get("text")))
    return [f for f in fields if f]


def _format_message(update, kind, message, text):
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    sender_chat = message.get("sender_chat") or {}
    via_bot = message.get("via_bot") or {}
    header = [
        "telegram",
        _field("update_id", update.get("update_id")),
        _field("kind", kind),
        _field("chat_id", chat.get("id")),
        _field("chat_type", chat.get("type")),
        _field("chat_title", _display_chat(chat)),
        _field("message_id", message.get("message_id")),
        _field("thread_id", message.get("message_thread_id")),
        _bool_field("is_topic", bool(message.get("is_topic_message"))),
        _field("from", _display_user(sender)),
        _field("from_id", sender.get("id")),
        _bool_field("from_is_bot", bool(sender.get("is_bot"))),
        _field("sender_chat", _display_chat(sender_chat)),
        _field("sender_chat_id", sender_chat.get("id")),
        _field("via_bot", _display_user(via_bot)),
        _bool_field("automatic_forward", bool(message.get("is_automatic_forward"))),
    ]
    header.extend(_forward_fields(message))
    header.extend(_reply_fields(message))
    header = " ".join(f for f in header if f)
    return f"[{header}]\n{text}"


def _extract_message(update):
    for kind in ("message", "edited_message", "channel_post", "edited_channel_post"):
        message = update.get(kind)
        if message:
            return kind, message
    return "unsupported", None


# ---- attachments -----------------------------------------------------------
# Files from ALLOWED chats are downloaded via the Bot API into a local inbox
# (inside the gitignored memory/ tree) so the agent can actually read them;
# the saved path is announced in the message text it sees. Disallowed chats
# are never fetched. getFile's own 20MB bot limit is enforced as our cap too.
_MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
_ATTACHMENT_SINGLE_KINDS = ("document", "video", "audio", "voice", "animation", "video_note", "sticker")


def _attachment_info(message):
    """(kind, file_id, file_name, mime, size) of the message's file, or None."""
    for kind in _ATTACHMENT_SINGLE_KINDS:
        item = (message or {}).get(kind)
        if item:
            return (kind, item.get("file_id"), item.get("file_name"),
                    item.get("mime_type"), item.get("file_size"))
    photos = (message or {}).get("photo") or []
    if photos:
        best = max(photos, key=lambda p: p.get("file_size") or 0)
        return ("photo", best.get("file_id"), None, "image/jpeg", best.get("file_size"))
    return None


def _safe_filename(name, fallback):
    name = os.path.basename(str(name or fallback))
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name).strip("._") or str(fallback)
    return name[:120]


def _attachments_dir():
    configured = os.environ.get("METTACLAW_TELEGRAM_ATTACHMENTS_DIR", "")
    if configured:
        return configured
    base = os.path.dirname(_offset_path or "") or "."
    return os.path.join(base, "memory", "attachments")


def _download_attachment(message):
    """Fetch the message's attachment; return an announcement line or None.

    Never raises, and never includes the token or a tokened URL in its output
    (transport exceptions are reduced to their type name)."""
    info = _attachment_info(message)
    if not info:
        return None
    kind, file_id, file_name, mime, size = info
    label = f"{kind} {file_name or file_id or '?'}" \
        + (f", {mime}" if mime else "") + (f", {size}b" if size else "")
    if not file_id:
        return f"[attachment {label} — no file_id]"
    if size and size > _MAX_ATTACHMENT_BYTES:
        return f"[attachment {label} — exceeds {_MAX_ATTACHMENT_BYTES}b cap, not downloaded]"
    try:
        resp = requests.get(_api("getFile"), params={"file_id": file_id}, timeout=30)
        resp.raise_for_status()
        remote_path = (resp.json().get("result") or {}).get("file_path")
        if not remote_path:
            return f"[attachment {label} — getFile returned no path]"
        dest_dir = _attachments_dir()
        os.makedirs(dest_dir, exist_ok=True)
        base = _safe_filename(file_name or os.path.basename(remote_path), (file_id or "file")[:16])
        dest = os.path.join(dest_dir, f"{(message or {}).get('message_id', 'x')}-{base}")
        partial = dest + ".part"
        url = f"{_api_base()}/file/bot{_token}/{remote_path}"
        try:
            with requests.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                written = 0
                with open(partial, "wb") as f:
                    for chunk in r.iter_content(65536):
                        written += len(chunk)
                        if written > _MAX_ATTACHMENT_BYTES:
                            raise ValueError("size cap exceeded mid-download")
                        f.write(chunk)
            os.replace(partial, dest)
        finally:
            try:
                os.unlink(partial)
            except FileNotFoundError:
                pass
        return f"[attachment saved: {dest} ({label})]"
    except Exception as exc:
        return f"[attachment {label} — download failed: {type(exc).__name__}]"


def _append_update_log(update, kind, message, allowed, queued, note=""):
    if not _log_path:
        return True
    chat = (message or {}).get("chat") or {}
    sender = (message or {}).get("from") or {}
    text = (message or {}).get("text")
    caption = (message or {}).get("caption")
    record = {
        "received_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "update_id": update.get("update_id"),
        "kind": kind,
        "allowed": bool(allowed),
        "queued": bool(queued),
        "note": note,
        "chat_id": str(chat.get("id", "")),
        "chat_type": chat.get("type", ""),
        "chat_title": _display_chat(chat),
        "message_id": (message or {}).get("message_id"),
        "from": _display_user(sender),
        "from_id": str(sender.get("id", "")),
        "from_is_bot": bool(sender.get("is_bot")),
        "text": text if allowed else None,
        "caption": caption if allowed else None,
        "raw": update if allowed else None,
    }
    try:
        parent = os.path.dirname(_log_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        with _log_lock:
            with open(_log_path, "a", encoding="utf-8") as f:
                f.write(line)
        return True
    except Exception as exc:
        print("[telegram] update log error:", exc)
        return False


def _set_last(chat_id, text, from_bot=False):
    global _last_chat_id
    with _msg_lock:
        _last_chat_id = str(chat_id)
        _pending_messages.append((_last_chat_id, str(text), bool(from_bot)))
        del _pending_messages[:-50]


def getLastMessage():
    global _reply_chat_id, _last_message_is_human, _last_from_bot
    with _msg_lock:
        if not _pending_messages:
            _last_message_is_human = False
            return ""
        item = _pending_messages.pop(0)
        if len(item) == 2:
            _reply_chat_id, msg = item
            from_bot = False
        else:
            _reply_chat_id, msg, from_bot = item
        _last_from_bot = bool(from_bot)
        _last_message_is_human = not _last_from_bot
        return msg


def lastMessageIsHuman():
    # Janus maps Python bools as grounded objects in PeTTa; use a tiny numeric
    # flag so MeTTa can convert it to a native boolean with ==.
    return 1 if _last_message_is_human else 0


def lastMessageFromBot():
    return _last_from_bot


def _load_offset():
    global _offset
    if not _offset_path:
        return
    try:
        with open(_offset_path, "r", encoding="utf-8") as f:
            value = f.read().strip()
        if value:
            _offset = int(value)
    except FileNotFoundError:
        return
    except Exception as exc:
        print("[telegram] offset load error:", exc)


def _save_offset():
    if not _offset_path or _offset is None:
        return
    try:
        parent = os.path.dirname(_offset_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        tmp = _offset_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(str(_offset))
        os.replace(tmp, _offset_path)
    except Exception as exc:
        print("[telegram] offset save error:", exc)


def recent_activity(n=10, chat=None, snippet_chars=110):
    """Short-term memory: the last n allowed messages from the local update
    log as '[hh:mm chat sender: text…]', oldest→newest. Always in context, so
    the agent keeps group-dynamics awareness (who spoke, when, was I last?)
    across turns — the vericlaw/godelclaw last-k-messages continuity, kept
    sweetly simple. Never raises (janus boundary)."""
    try:
        n = max(1, int(n))
        if not _log_path or not os.path.exists(_log_path):
            return ""
        if chat is None:
            # ambient per-turn STM: cheap tail read
            with open(_log_path, "rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - 65536))
                lines = f.read().decode("utf-8", "replace").splitlines()
        else:
            # explicit per-chat recall: stream the whole log (reaches back to
            # the beginning of local logging)
            with open(_log_path, encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        entries = []
        for line in lines:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not rec.get("allowed") or not rec.get("text"):
                continue
            if chat is not None:
                needle = str(chat).lower()
                if (needle not in str(rec.get("chat_title", "")).lower()
                        and needle != str(rec.get("chat_id", ""))):
                    continue
            ts = str(rec.get("received_at", ""))[11:16]  # ISO -> hh:mm
            snippet = " ".join(str(rec.get("text", "")).split())
            if len(snippet) > snippet_chars:
                snippet = snippet[:snippet_chars] + "…"
            entries.append(f"[{ts} {rec.get('chat_title', '?')} "
                           f"{rec.get('from', '?')}: {snippet}]")
        return " ".join(entries[-n:])
    except Exception as exc:
        print("[telegram] recent_activity error:", exc)
        return ""


def _operator_ids():
    """Sender ids allowed to use the model/quota controls (spending levers)."""
    raw = os.environ.get("METTACLAW_TELEGRAM_OPERATOR_IDS", "")
    return {part.strip() for part in raw.split(",") if part.strip()}


def _is_operator(sender):
    return str((sender or {}).get("id", "")) in _operator_ids()


def _models_keyboard():
    """Inline keyboard of switchable models: tap a button to switch (handled
    by _handle_callback_query, zero LLM involvement)."""
    import synthetic_llm
    current = synthetic_llm.current_model()
    rows = []
    for m in synthetic_llm.model_ids():
        if len(("model:" + m).encode("utf-8")) > 64:  # telegram limit
            continue
        label = ("● " if m == current else "") + m
        rows.append([{"text": label, "callback_data": "model:" + m}])
    return {"inline_keyboard": rows}


def _handle_callback_query(cq):
    """A tapped, namespaced model button (callback_data 'model:<id>') from an
    operator: switch, acknowledge, update the menu message."""
    import synthetic_llm
    data = str(cq.get("data") or "")
    message = cq.get("message") or {}
    chat = message.get("chat") or {}
    try:
        if not data.startswith("model:"):
            return "callback_ignored"
        if not _chat_is_allowed(chat):
            return "callback_disallowed_chat"
        if not _is_operator(cq.get("from")):
            requests.post(_api("answerCallbackQuery"), json={
                "callback_query_id": cq.get("id"),
                "text": "model switching is operator-only",
            }, timeout=15)
            return "callback_not_operator"
        # Stop Telegram's spinner FIRST: the client shows a loading state until
        # the callback is answered, so acknowledging before doing the work is
        # the difference between "instant" and "stuck" from the operator's side.
        started = time.time()
        requests.post(_api("answerCallbackQuery"), json={
            "callback_query_id": cq.get("id"), "text": "switching…",
        }, timeout=15)
        reply = synthetic_llm.set_model(data[len("model:"):])
        print("[telegram] model switch handled in %.2fs" % (time.time() - started))
        requests.post(_api("editMessageText"), json={
            "chat_id": chat.get("id"),
            "message_id": message.get("message_id"),
            "text": str(reply)[:3800],
            "reply_markup": _models_keyboard(),
        }, timeout=15)
        return "callback_model_switch"
    except Exception as exc:
        print("[telegram] callback error:", exc)
        return "callback_error"


_bot_username = None


def _my_username():
    """This bot's @username via getMe, cached; "" while unknown."""
    global _bot_username
    if _bot_username is None:
        try:
            r = requests.get(_api("getMe"), timeout=15).json()
            name = str((r.get("result") or {}).get("username") or "")
            if name:
                _bot_username = name
            return name
        except Exception:
            return ""
    return _bot_username


def _peek_slash_command(text, sender):
    """Would _handle_slash_command take this? Decided without network calls, so
    the poll thread can hand it off and keep polling."""
    stripped = (text or "").strip()
    if not stripped.startswith("/"):
        return None
    head = stripped.split(None, 1)[0]
    cmd = head.split("@", 1)[0].lower()
    if cmd not in ("/model", "/models", "/quota"):
        return None
    if "@" in head:
        mine = _my_username().lower()
        if not mine or head.split("@", 1)[1].lower() != mine:
            return "slash_command_other_bot:" + head.split("@", 1)[1].lower()
    if not _is_operator(sender):
        return None
    return "slash_command:" + cmd


def _handle_slash_command(chat, sender, text):
    """Deterministic /model, /models, /quota handling inside the poll thread.

    Zero LLM involvement: the reply is sent directly and the message is NOT
    queued for the agent, so a command costs no tokens and works even while
    the agent rests. A model switch takes effect on the agent's next turn
    (chat() reads SYNTHETIC_MODEL per call). Returns a log note when handled,
    None otherwise."""
    stripped = (text or "").strip()
    if not stripped.startswith("/"):
        return None
    parts = stripped.split(None, 1)
    head = parts[0]
    cmd = head.split("@", 1)[0].lower()  # '/model@SomeBot' -> '/model'
    if "@" in head and cmd in ("/model", "/models", "/quota"):
        # An @suffix names the addressee. Answering a command aimed at a
        # DIFFERENT bot switched the wrong agent's model live (2026-07-19).
        target = head.split("@", 1)[1].lower()
        mine = _my_username().lower()
        if not mine or target != mine:
            return "slash_command_other_bot:" + target
    arg = parts[1].strip() if len(parts) > 1 else ""
    if cmd not in ("/model", "/models", "/quota"):
        return None
    if not _is_operator(sender):
        # Spending levers are operator-only. For anyone else the message just
        # flows to the agent as ordinary conversation.
        return None
    try:
        import synthetic_llm
        if cmd == "/models":
            requests.post(_api("sendMessage"), json={
                "chat_id": chat.get("id"),
                "text": "tap to switch:",
                "reply_markup": _models_keyboard(),
            }, timeout=15)
            return "slash_command:/models"
        elif cmd == "/quota":
            reply = synthetic_llm.quota()
        elif arg:
            reply = synthetic_llm.set_model(arg)
        else:
            reply = (
                f"active model: {synthetic_llm.current_model()} — "
                "/model <name> to switch, /models to list, /quota for budget"
            )
        send_message_to_chat(str(chat.get("id", "")), str(reply)[:3800])
        return "slash_command:" + cmd
    except Exception as exc:
        print("[telegram] slash command error:", exc)
        return "slash_command_error:" + cmd


def _poll_loop():
    global _offset
    while _running:
        try:
            params = {"timeout": 20}
            if _offset is not None:
                params["offset"] = _offset
            resp = requests.get(_api("getUpdates"), params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            for update in data.get("result", []):
                update_id = int(update["update_id"])
                if "callback_query" in update:
                    cq = update["callback_query"] or {}
                    threading.Thread(target=_handle_callback_query,
                                     args=(cq,), daemon=True).start()
                    cb_note = "callback_dispatched"
                    cb_msg = cq.get("message") or {}
                    # log the real allowlist verdict; the outcome is cb_note
                    # (a False here on a successful switch is a lying record)
                    _append_update_log(update, "callback_query", cb_msg,
                                       _chat_is_allowed(cb_msg.get("chat") or {}),
                                       False, cb_note)
                    _offset = update_id + 1
                    _save_offset()
                    continue
                kind, message = _extract_message(update)
                note = ""
                allowed = False
                queued = False
                text = None
                if not message:
                    note = "unsupported_update"
                else:
                    chat = message.get("chat") or {}
                    allowed = _chat_is_allowed(chat)
                    if allowed:
                        _chat_titles[str(chat.get("id", ""))] = \
                            _display_chat(chat)
                    text = message.get("text") or message.get("caption")
                    if not allowed:
                        note = "disallowed_chat"
                    else:
                        attachment_note = _download_attachment(message)
                        if attachment_note:
                            text = (text + "\n" if text else "") + attachment_note
                        if not text:
                            note = "no_text_or_caption"
                        else:
                            command_note = _peek_slash_command(text,
                                                              message.get("from"))
                            if command_note:
                                # Operator commands answer on their own thread:
                                # a slow provider call must not stall polling
                                # for every other message behind it.
                                note = command_note
                                threading.Thread(
                                    target=_handle_slash_command,
                                    args=(chat, message.get("from"), text),
                                    daemon=True).start()
                            else:
                                queued = True
                if not _append_update_log(update, kind, message, allowed, queued, note):
                    print("[telegram] continuing after update log failure")
                _offset = update_id + 1
                _save_offset()
                if queued:
                    chat = message.get("chat") or {}
                    sender = message.get("from") or {}
                    _set_last(
                        chat.get("id", ""),
                        _format_message(update, kind, message, text),
                        bool(sender.get("is_bot")),
                    )
        except Exception as exc:
            print("[telegram] poll error:", exc)
            time.sleep(5)


def start_telegram(token="", chat_id=""):
    global _running, _thread, _token, _allowed_chat_ids, _allow_private_chats, _offset_path, _log_path
    _token = str(
        token
        or os.environ.get("METTACLAW_TELEGRAM_BOT_TOKEN")
        or os.environ.get("TELEGRAM_BOT_TOKEN")
        or ""
    )
    configured_ids = ",".join(
        part
        for part in [
            str(chat_id or ""),
            os.environ.get("METTACLAW_TELEGRAM_CHAT_ID", ""),
            os.environ.get("TELEGRAM_CHAT_ID", ""),
            os.environ.get("METTACLAW_TELEGRAM_ALLOWED_CHAT_IDS", ""),
        ]
        if part
    )
    _allowed_chat_ids = _split_chat_ids(configured_ids)
    _allow_private_chats = (
        os.environ.get("METTACLAW_TELEGRAM_ALLOW_PRIVATE", "1").lower()
        not in {"0", "false", "no"}
    )
    _offset_path = os.environ.get("METTACLAW_TELEGRAM_OFFSET_PATH", "")
    _log_path = os.environ.get("METTACLAW_TELEGRAM_LOG_PATH", "")
    if not _token:
        print("[telegram] disabled: set METTACLAW_TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN")
        return None
    if _thread and _thread.is_alive():
        return _thread
    _load_offset()
    _running = True
    _thread = threading.Thread(target=_poll_loop, daemon=True)
    _thread.start()
    return _thread


def stop_telegram():
    global _running
    _running = False


def _reply_target(chat_id=""):
    if chat_id:
        return str(chat_id)
    with _msg_lock:
        return _reply_chat_id or _last_chat_id


def _log_outbound(chat_id, text):
    """Record the agent's own send in the local update log so the short-term
    memory (recent_activity) shows both sides of the conversation."""
    if not _log_path:
        return
    try:
        record = {
            "received_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "kind": "outbound",
            "allowed": True,
            "queued": False,
            "note": "own_send",
            "chat_id": str(chat_id),
            "chat_title": _chat_titles.get(str(chat_id), str(chat_id)),
            "from": "me",
            "from_is_bot": True,
            "text": str(text),
        }
        line = json.dumps(record, ensure_ascii=False,
                          separators=(",", ":")) + "\n"
        with _log_lock:
            with open(_log_path, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception as exc:
        print("[telegram] outbound log error:", exc)


def send_message(text, chat_id=""):
    chat_id = _reply_target(chat_id)
    if not _token or not chat_id:
        print("[telegram] cannot send: missing token or chat id")
        return
    try:
        body = str(text).replace("\\n", "\n")
        resp = requests.post(
            _api("sendMessage"),
            json={"chat_id": chat_id, "text": body},
            timeout=30,
        )
        delivered = False
        try:
            delivered = bool(resp.ok and resp.json().get("ok"))
        except ValueError:
            pass
        if delivered:
            # STM records only what Telegram actually accepted.
            _log_outbound(chat_id, body)
        else:
            print(f"[telegram] send rejected (HTTP {resp.status_code})")
    except requests.exceptions.RequestException as exc:
        # A transient network failure on send must never cross Janus and kill the
        # loop (the same failure class that crashed Lila via synthetic_llm).
        print(f"[telegram] send failed ({type(exc).__name__}): {exc}")


def send_message_to_chat(chat_id, text):
    return send_message(text, chat_id=chat_id)


def _send_upload(method, field, path, caption, chat_id):
    """POST one file to Telegram. Returns a result string the agent can read —
    success or the actual reason, never a silent failure."""
    chat_id = _reply_target(chat_id)
    path = str(path)
    token = _token or os.environ.get("METTACLAW_TELEGRAM_BOT_TOKEN", "")
    if not os.path.isfile(path):
        # Check the file first: "no such file" is the answer the caller can act
        # on, and it is the common case (a placeholder path copied verbatim).
        return "send failed: no such file: " + path
    if not token:
        return "send failed: no bot token configured"
    if not chat_id:
        return ("send failed: no chat to send to — pass one explicitly, "
                "e.g. (send-image \"/path.svg\" \"caption\" \"111000111\")")
    size = os.path.getsize(path)
    if size > 50 * 1024 * 1024:
        return "send failed: %s is %d bytes; Telegram's limit is 50MB" % (path, size)
    try:
        with open(path, "rb") as fh:
            data = {"chat_id": chat_id}
            if caption:
                data["caption"] = str(caption).replace("\\n", "\n")[:1024]
            resp = requests.post(_api(method, token), data=data,
                                 files={field: (os.path.basename(path), fh)},
                                 timeout=120)
        try:
            ok = bool(resp.ok and resp.json().get("ok"))
        except ValueError:
            ok = False
        if not ok:
            detail = ""
            try:
                detail = ": " + str(resp.json().get("description", ""))[:160]
            except ValueError:
                pass
            return "send failed (HTTP %s)%s" % (resp.status_code, detail)
        _log_outbound(chat_id, "[%s %s] %s" % (field, os.path.basename(path),
                                               caption or ""))
        return "sent %s (%d bytes) to chat %s" % (os.path.basename(path), size,
                                                  chat_id)
    except requests.exceptions.RequestException as exc:
        return "send failed (%s): %s" % (type(exc).__name__, exc)


def _rasterize_svg(path):
    """SVG -> PNG so it previews inline. Returns the PNG path, or "" if no
    converter is available (the caller then falls back to sendDocument)."""
    out = os.path.join(tempfile.gettempdir(),
                       os.path.basename(path).rsplit(".", 1)[0] + ".png")
    try:
        import cairosvg
        cairosvg.svg2png(url=path, write_to=out, output_width=1400)
        return out
    except Exception:
        pass
    for tool in (["rsvg-convert", "-w", "1400", "-o", out, path],
                 ["inkscape", "--export-type=png", "--export-width=1400",
                  "--export-filename=" + out, path],
                 ["convert", "-density", "150", path, out]):
        try:
            if subprocess.run(tool, capture_output=True,
                              timeout=60).returncode == 0 and os.path.isfile(out):
                return out
        except (OSError, subprocess.SubprocessError):
            continue
    return ""


def send_file(path, caption="", chat_id=""):
    """Send any file as a document (appears as an attachment)."""
    return _send_upload("sendDocument", "document", path, caption, chat_id)


def send_image(path, caption="", chat_id=""):
    """Send an image so it previews inline. SVG is rasterized to PNG when a
    converter exists; otherwise it is sent as a document with a note, because
    Telegram cannot preview SVG."""
    path = str(path)
    if path.lower().endswith(".svg"):
        png = _rasterize_svg(path)
        if png:
            result = _send_upload("sendPhoto", "photo", png, caption, chat_id)
            try:
                os.unlink(png)
            except OSError:
                pass
            return result
        note = (caption + " " if caption else "") + "(SVG: no rasterizer here, sent as a file)"
        return _send_upload("sendDocument", "document", path, note, chat_id)
    return _send_upload("sendPhoto", "photo", path, caption, chat_id)
