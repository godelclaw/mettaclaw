import os
import json
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


def _api(method):
    return f"https://api.telegram.org/bot{_token}/{method}"


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
                    text = message.get("text") or message.get("caption")
                    if not allowed:
                        note = "disallowed_chat"
                    elif not text:
                        note = "no_text_or_caption"
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


def send_message(text, chat_id=""):
    chat_id = _reply_target(chat_id)
    if not _token or not chat_id:
        print("[telegram] cannot send: missing token or chat id")
        return
    try:
        requests.post(
            _api("sendMessage"),
            json={"chat_id": chat_id, "text": str(text).replace("\\n", "\n")},
            timeout=30,
        )
    except requests.exceptions.RequestException as exc:
        # A transient network failure on send must never cross Janus and kill the
        # loop (the same failure class that crashed Lila via synthetic_llm).
        print(f"[telegram] send failed ({type(exc).__name__}): {exc}")


def send_message_to_chat(chat_id, text):
    return send_message(text, chat_id=chat_id)
