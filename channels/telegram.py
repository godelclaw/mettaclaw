import os
import threading
import time

import requests

_running = False
_thread = None
_token = ""
_allowed_chat_ids = set()
_allow_private_chats = True
_last_chat_id = ""
_last_message = ""
_offset = None
_offset_path = ""
_msg_lock = threading.Lock()


def _api(method):
    return f"https://api.telegram.org/bot{_token}/{method}"


def _split_chat_ids(raw):
    return {part.strip() for part in str(raw or "").split(",") if part.strip()}


def _chat_is_allowed(chat):
    chat_id = str(chat.get("id", ""))
    if _allow_private_chats and chat.get("type") == "private":
        return True
    return chat_id in _allowed_chat_ids


def _set_last(chat_id, name, text):
    global _last_chat_id, _last_message
    with _msg_lock:
        _last_chat_id = str(chat_id)
        msg = f"{name}: {text}" if name else str(text)
        _last_message = msg if not _last_message else _last_message + " | " + msg


def getLastMessage():
    global _last_message
    with _msg_lock:
        msg = _last_message
        _last_message = ""
        return msg


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
                _offset = int(update["update_id"]) + 1
                _save_offset()
                message = update.get("message") or update.get("edited_message")
                if not message:
                    continue
                chat = message.get("chat") or {}
                if not _chat_is_allowed(chat):
                    continue
                text = message.get("text")
                if not text:
                    continue
                sender = message.get("from") or {}
                name = sender.get("username") or sender.get("first_name") or ""
                _set_last(chat.get("id", ""), name, text)
        except Exception as exc:
            print("[telegram] poll error:", exc)
            time.sleep(5)


def start_telegram(token="", chat_id=""):
    global _running, _thread, _token, _allowed_chat_ids, _allow_private_chats, _offset_path
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


def send_message(text):
    chat_id = _last_chat_id
    if not _token or not chat_id:
        print("[telegram] cannot send: missing token or chat id")
        return
    requests.post(
        _api("sendMessage"),
        json={"chat_id": chat_id, "text": str(text).replace("\\n", "\n")},
        timeout=30,
    )
