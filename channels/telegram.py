import os
import json
import math
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
_last_arm_tier = "full"
_pending_messages = []
_offset = None
_offset_path = ""
_log_path = ""
_msg_lock = threading.Lock()
_log_lock = threading.Lock()
_energy_lock = threading.RLock()
_chat_titles = {}  # chat_id -> last-seen display title (for outbound records)
# Rest state. The poll thread keeps running while the agent's main loop
# sleeps, so it can answer "he is resting" and end the rest on request.
_sleep_until = 0.0          # epoch when the current rest ends; 0 = awake
_wake_event = threading.Event()
_wake_lock = threading.Lock()
_wake_reason = ""
_rest_notice_sent = False
_health_lock = threading.RLock()
_health_state = {}
_health_last_write = 0.0
_effect_lock = threading.RLock()
_effect_turn = None
_effect_sends = set()

_CONTROL_COMMANDS = (
    "/model", "/models", "/mode", "/modes", "/quota", "/wake",
    "/energy", "/health", "/claude_code_authorization",
)

_MENU_COMMANDS = (
    ("mode", "Show or switch the cognitive loop mode"),
    ("modes", "List cognitive loop modes"),
    ("model", "Show or switch the language model"),
    ("models", "List language models"),
    ("energy", "Show per-sender arming energy"),
    ("health", "Show runtime, channel, and memory health"),
    ("quota", "Show model budget"),
    ("wake", "End the current rest"),
)


def _health_path():
    configured = os.environ.get("METTACLAW_TELEGRAM_HEALTH_PATH", "")
    if configured:
        return configured
    state_home = os.environ.get(
        "XDG_STATE_HOME", os.path.expanduser("~/.local/state"))
    instance = os.environ.get("METTACLAW_INSTANCE", "default")
    return os.path.join(state_home, "pettaclaw", instance,
                        "telegram-health.json")


def _health_update(force=False, **fields):
    """Atomically publish non-secret liveness facts for an external monitor."""
    global _health_last_write
    now = time.time()
    with _health_lock:
        _health_state.update(fields)
        _health_state["observed_at"] = now
        if not force and now - _health_last_write < 15:
            return
        path = _health_path()
        directory = os.path.dirname(path) or "."
        try:
            os.makedirs(directory, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".telegram-health-",
                                       dir=directory, text=True)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(_health_state, fh, sort_keys=True)
                    fh.write("\n")
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, path)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
            _health_last_write = now
        except OSError as exc:
            print("[telegram] health write failed:", type(exc).__name__)


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


# ---- arming energy ---------------------------------------------------------
# Every human message arms a fresh loop budget. Tiers size that burst per
# sender — full/mid/light — so a high-volume conversational partner does not
# hold the agent at maximum indefinitely, while everyone still wakes the agent
# and still gets answered. The map persists in a small JSON file the agent
# (via energy skills) and the operator (via /energy) both edit.

ENERGY_TIERS = ("full", "mid", "light")


def _tier_loops(tier):
    defaults = {"full": 50, "mid": 30, "light": 10}
    envnames = {"full": "METTACLAW_LOOPS_FULL", "mid": "METTACLAW_LOOPS_MID",
                "light": "METTACLAW_LOOPS_LIGHT"}
    # Live override: energy.json tier_loops takes priority over env and defaults
    try:
        import json as _json
        with open(_energy_path()) as _f:
            _edata = _json.load(_f)
        _tl = _edata.get('tier_loops', {})
        if tier in _tl:
            return max(1, int(_tl[tier]))
    except Exception:
        pass  # silently fall through to env/defaults
    try:
        return max(1, int(os.environ.get(envnames[tier], defaults[tier])))
    except (KeyError, ValueError, TypeError):
        return 50


def _energy_path():
    return os.environ.get("METTACLAW_ENERGY_PATH", "memory/energy.json")


def _sender_names_env():
    """Optional 'id:Name,id:Name' labels for the /energy menu."""
    out = {}
    for part in os.environ.get("METTACLAW_TELEGRAM_SENDER_NAMES", "").split(","):
        if ":" in part:
            sid, name = part.split(":", 1)
            if sid.strip() and name.strip():
                out[sid.strip()] = name.strip()
    return out


def _energy_load():
    """The energy map; seeded on first use from the legacy light-arm env."""
    with _energy_lock:
        try:
            with open(_energy_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                default = data.get("default", "full")
                if default not in ENERGY_TIERS:
                    default = "full"
                raw_senders = data.get("senders", {})
                raw_names = data.get("names", {})
                senders = ({str(k): v for k, v in raw_senders.items()
                            if v in ENERGY_TIERS}
                           if isinstance(raw_senders, dict) else {})
                names = ({str(k): str(v) for k, v in raw_names.items()}
                         if isinstance(raw_names, dict) else {})
                return {"default": default, "senders": senders,
                        "names": names}
        except (OSError, ValueError, TypeError):
            pass
        senders = {}
        for sid in os.environ.get(
                "METTACLAW_TELEGRAM_LIGHT_ARM_IDS", "").split(","):
            if sid.strip():
                senders[sid.strip()] = "light"
        return {"default": "full", "senders": senders,
                "names": _sender_names_env()}


def _energy_save(data):
    with _energy_lock:
        path = _energy_path()
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, path)
            return True
        except OSError as exc:
            print("[telegram] energy save failed:", exc)
            return False


def _tier_for_sender(sender):
    data = _energy_load()
    return data["senders"].get(str((sender or {}).get("id", "")),
                               data.get("default", "full"))


def _energy_label(data, sid):
    return data.get("names", {}).get(sid) or _sender_names_env().get(sid) or sid


def energy_view():
    """Human-readable summary the agent can print."""
    data = _energy_load()
    d = data.get("default", "full")
    parts = ["default: %s(%d)" % (d, _tier_loops(d))]
    for sid, tier in sorted(data.get("senders", {}).items()):
        parts.append("%s: %s(%d)" % (_energy_label(data, sid), tier,
                                     _tier_loops(tier)))
    return " | ".join(parts)


def energy_set(who, tier):
    """Set the arming tier for 'default', a sender id, or a known name."""
    tier = str(tier).strip().lower()
    alias = {"50": "full", "30": "mid", "10": "light"}
    tier = alias.get(tier, tier)
    if tier not in ENERGY_TIERS:
        return "energy-set failed: tier must be full, mid or light (got %r)" % tier
    who = str(who).strip()
    with _energy_lock:
        data = _energy_load()
        if who.lower() in ("default", "everyone", "*"):
            data["default"] = tier
            ok = _energy_save(data)
            return ("default arming set to %s(%d)" % (tier, _tier_loops(tier))
                    if ok else "energy-set failed: could not persist")
        sid = who
        if not who.lstrip("-").isdigit():
            matches = [k for k, v in data.get("names", {}).items()
                       if v.lower() == who.lower()]
            if not matches:
                matches = [k for k, v in _sender_names_env().items()
                           if v.lower() == who.lower()]
            if not matches:
                return ("energy-set failed: unknown name %r — use a numeric "
                        "sender id, or one of: %s" % (who, ", ".join(
                            sorted(set(data.get("names", {}).values())
                                   | set(_sender_names_env().values())))
                            or "(none known)"))
            sid = matches[0]
        data["senders"][sid] = tier
        data.setdefault("names", {}).update({
            sid: data.get("names", {}).get(sid)
            or _sender_names_env().get(sid, sid)})
        ok = _energy_save(data)
        return ("%s arming set to %s(%d)" % (_energy_label(data, sid), tier,
                                             _tier_loops(tier))
                if ok else "energy-set failed: could not persist")


def _set_last(chat_id, text, from_bot=False, arm_tier="full"):
    global _last_chat_id
    with _msg_lock:
        _last_chat_id = str(chat_id)
        _pending_messages.append(
            (_last_chat_id, str(text), bool(from_bot), str(arm_tier)))
        del _pending_messages[:-50]


def getLastMessage():
    global _reply_chat_id, _last_message_is_human, _last_from_bot
    global _last_arm_tier
    with _msg_lock:
        if not _pending_messages:
            _last_message_is_human = False
            _last_arm_tier = "full"
            return ""
        item = _pending_messages.pop(0)
        # Tuples have grown over time; older queued entries stay readable.
        tier = "full"
        if len(item) == 2:
            _reply_chat_id, msg = item
            from_bot = False
        elif len(item) == 3:
            _reply_chat_id, msg, from_bot = item
        else:
            _reply_chat_id, msg, from_bot, tier = item
        _last_from_bot = bool(from_bot)
        _last_message_is_human = not _last_from_bot
        _last_arm_tier = str(tier) if _last_message_is_human else "full"
        return msg


def getActivityBatch():
    """Drain every pending message into one chronological batch — the
    context-centric turn: accumulated activity is OBSERVATION for the next
    cognitive tick, not a per-message to-do list. Each entry keeps its own
    metadata header (sender, chat, ids, from_is_bot) as already formatted.
    Reply routing and energy accounting follow the NEWEST HUMAN message when
    present (existing tier machinery, unchanged), else the newest message."""
    global _reply_chat_id, _last_message_is_human, _last_from_bot
    global _last_arm_tier
    with _msg_lock:
        if not _pending_messages:
            _last_message_is_human = False
            _last_arm_tier = "full"
            return ""
        items = _pending_messages[:]
        del _pending_messages[:]
    texts = []
    newest_human = None
    newest = None
    for item in items:
        tier = "full"
        if len(item) == 2:
            chat, msg = item
            from_bot = False
        elif len(item) == 3:
            chat, msg, from_bot = item
        else:
            chat, msg, from_bot, tier = item
        texts.append(str(msg))
        newest = (chat, from_bot, tier)
        if not from_bot:
            newest_human = (chat, from_bot, tier)
    pick = newest_human or newest
    _reply_chat_id = str(pick[0])
    _last_from_bot = bool(pick[1])
    _last_message_is_human = not _last_from_bot
    _last_arm_tier = str(pick[2]) if _last_message_is_human else "full"
    return "\n".join(texts)


def lastMessageIsHuman():
    # Janus maps Python bools as grounded objects in PeTTa; use a tiny numeric
    # flag so MeTTa can convert it to a native boolean with ==.
    return 1 if _last_message_is_human else 0


def lastMessageArmLoops():
    """Loop count the last human message arms: the sender's energy tier."""
    tier = _last_arm_tier if _last_arm_tier in ENERGY_TIERS else "full"
    return _tier_loops(tier)


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
    across turns — bounded last-k-messages continuity, kept
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


def _request_wake(reason):
    """Interrupt a timed rest and retain truthful provenance for its result."""
    global _wake_reason
    with _wake_lock:
        _wake_reason = str(reason)
        _wake_event.set()


def _wake_for_operator_message(sender):
    """An authenticated operator message is itself an explicit wake request."""
    if not _is_operator(sender):
        return False
    _request_wake("operator message")
    return True


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


def _modes_keyboard():
    """Inline keyboard for the persistent cognitive-loop policy."""
    import loop_modes
    current = loop_modes.current_mode()
    rows = []
    for name in loop_modes.MODES:
        label = ("● " if name == current else "") + name
        rows.append([{"text": label, "callback_data": "mode:" + name}])
    return {"inline_keyboard": rows}


def _handle_callback_query(cq):
    """A tapped, namespaced model button (callback_data 'model:<id>') from an
    operator: switch, acknowledge, update the menu message."""
    import synthetic_llm
    data = str(cq.get("data") or "")
    message = cq.get("message") or {}
    chat = message.get("chat") or {}
    try:
        if data.startswith("energy:"):
            if not _chat_is_allowed(chat):
                return "callback_disallowed_chat"
            if not _is_operator(cq.get("from")):
                requests.post(_api("answerCallbackQuery"), json={
                    "callback_query_id": cq.get("id"),
                    "text": "energy tiers are operator-only",
                }, timeout=15)
                return "callback_not_operator"
            _, who, tier = data.split(":", 2)
            reply = energy_set(who, tier)
            requests.post(_api("answerCallbackQuery"), json={
                "callback_query_id": cq.get("id"), "text": str(reply)[:190],
            }, timeout=15)
            requests.post(_api("editMessageText"), json={
                "chat_id": chat.get("id"),
                "message_id": message.get("message_id"),
                "text": "arming energy — " + energy_view(),
                "reply_markup": _energy_keyboard(),
            }, timeout=15)
            return "callback_energy"
        if data.startswith("mode:"):
            if not _chat_is_allowed(chat):
                return "callback_disallowed_chat"
            if not _is_operator(cq.get("from")):
                requests.post(_api("answerCallbackQuery"), json={
                    "callback_query_id": cq.get("id"),
                    "text": "mode switching is operator-only",
                }, timeout=15)
                return "callback_not_operator"
            import loop_modes
            reply = loop_modes.set_mode(data[len("mode:"):])
            _request_wake("mode switch")
            requests.post(_api("answerCallbackQuery"), json={
                "callback_query_id": cq.get("id"), "text": str(reply)[:190],
            }, timeout=15)
            requests.post(_api("editMessageText"), json={
                "chat_id": chat.get("id"),
                "message_id": message.get("message_id"),
                "text": loop_modes.mode_view(),
                "reply_markup": _modes_keyboard(),
            }, timeout=15)
            return "callback_mode_switch"
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


def _energy_keyboard():
    """Inline keyboard for arming tiers: one row for the default, one per
    known sender. Tapping writes the persisted energy map — zero LLM cost."""
    data = _energy_load()
    cur_default = data.get("default", "full")
    rows = []
    row = []
    for tier in ENERGY_TIERS:
        mark = "● " if tier == cur_default else ""
        row.append({"text": "%severyone: %s(%d)" % (mark, tier, _tier_loops(tier)),
                    "callback_data": "energy:default:" + tier})
    rows.append(row)
    known = dict(_sender_names_env())
    known.update({sid: _energy_label(data, sid)
                  for sid in data.get("senders", {})})
    for sid, name in sorted(known.items(), key=lambda kv: kv[1].lower()):
        cur = data.get("senders", {}).get(sid, cur_default)
        row = []
        for tier in ENERGY_TIERS:
            mark = "● " if tier == cur else ""
            cbd = "energy:%s:%s" % (sid, tier)
            if len(cbd.encode("utf-8")) > 64:
                continue
            row.append({"text": "%s%s: %s" % (mark, name, tier),
                        "callback_data": cbd})
        if row:
            rows.append(row)
    return {"inline_keyboard": rows}


_bot_username = None


def _known_username():
    """Configured/cached bot identity, without any network operation."""
    return str(
        _bot_username
        or os.environ.get("METTACLAW_TELEGRAM_BOT_USERNAME", "")
    ).lstrip("@")


def _my_username():
    """This bot's @username via getMe, cached; "" while unknown."""
    global _bot_username
    configured = _known_username()
    if configured:
        _bot_username = configured
        return configured
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


def _maybe_rest_notice(chat, sender):
    """Tell the operator the agent is resting, and for how long, so they can
    decide whether to wait or /wake. Sent once per rest, not per message."""
    global _rest_notice_sent
    resting, left = rest_status()
    if not resting or _rest_notice_sent or not _is_operator(sender):
        return
    _rest_notice_sent = True
    wake_at = time.strftime("%H:%M", time.localtime(time.time() + left))
    mins, secs = left // 60, left % 60
    span = ("%dm%02ds" % (mins, secs)) if mins else ("%ds" % secs)
    try:
        send_message_to_chat(
            str(chat.get("id", "")),
            "\U0001F4A4 resting — wakes in %s (at %s). Your message is queued "
            "and will be read then; send /wake to end the rest now."
            % (span, wake_at))
    except Exception as exc:
        print("[telegram] rest notice failed:", exc)


def _peek_slash_command(text, sender):
    """Would _handle_slash_command take this? Decided without network calls, so
    the poll thread can hand it off and keep polling."""
    stripped = (text or "").strip()
    if not stripped.startswith("/"):
        return None
    head = stripped.split(None, 1)[0]
    cmd = head.split("@", 1)[0].lower()
    if cmd not in _CONTROL_COMMANDS:
        return None
    if "@" in head:
        # The polling path must not block on getMe. Identity is provisioned
        # alongside the token; an unknown addressed command is safely consumed.
        mine = _known_username().lower()
        if not mine or head.split("@", 1)[1].lower() != mine:
            return "slash_command_other_bot:" + head.split("@", 1)[1].lower()
    if not _is_operator(sender):
        return None
    return "slash_command:" + cmd


def _handle_slash_command(chat, sender, text):
    """Deterministic operator commands with zero LLM involvement.

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
    if "@" in head and cmd in _CONTROL_COMMANDS:
        # An @suffix names the addressee. Answering a command aimed at a
        # DIFFERENT bot switched the wrong agent's model live (2026-07-19).
        target = head.split("@", 1)[1].lower()
        mine = _known_username().lower()
        if not mine or target != mine:
            return "slash_command_other_bot:" + target
    arg = parts[1].strip() if len(parts) > 1 else ""
    if cmd not in _CONTROL_COMMANDS:
        return None
    if not _is_operator(sender):
        # Operator controls are not available to other senders. Their message
        # flows to the agent as ordinary conversation instead.
        return None
    try:
        if cmd == "/wake":
            # Wake silently. The agent's next real reply is the confirmation;
            # a separate "awake" acknowledgement is just noise in the chat.
            _request_wake("/wake")
            return "slash_command:/wake"
        if cmd == "/claude_code_authorization":
            import claude_bridge
            state = not claude_bridge.authorized()
            reply = claude_bridge.set_authorized(state)
            send_message_to_chat(str(chat.get("id", "")), reply)
            return "slash_command:/claude_code_authorization"
        if cmd == "/energy":
            requests.post(_api("sendMessage"), json={
                "chat_id": chat.get("id"),
                "text": "arming energy — " + energy_view(),
                "reply_markup": _energy_keyboard(),
            }, timeout=15)
            return "slash_command:/energy"
        if cmd == "/health":
            import runtime_health
            send_message_to_chat(str(chat.get("id", "")),
                                 runtime_health.report())
            return "slash_command:/health"
        if cmd in ("/mode", "/modes"):
            import loop_modes
            if cmd == "/modes":
                requests.post(_api("sendMessage"), json={
                    "chat_id": chat.get("id"),
                    "text": loop_modes.mode_view(),
                    "reply_markup": _modes_keyboard(),
                }, timeout=15)
                return "slash_command:/modes"
            if arg:
                reply = loop_modes.set_mode(arg)
                _request_wake("mode switch")
            else:
                reply = (loop_modes.mode_view()
                         + " — /mode <name> to switch, /modes to list")
            send_message_to_chat(str(chat.get("id", "")), str(reply)[:3800])
            return "slash_command:/mode"
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
            try:
                poll_timeout = min(30, max(1, int(os.environ.get(
                    "METTACLAW_TELEGRAM_POLL_TIMEOUT", "20"))))
            except ValueError:
                poll_timeout = 20
            try:
                request_timeout = max(poll_timeout + 2, int(os.environ.get(
                    "METTACLAW_TELEGRAM_REQUEST_TIMEOUT", "30")))
            except ValueError:
                request_timeout = max(poll_timeout + 2, 30)
            params = {"timeout": poll_timeout}
            if _offset is not None:
                params["offset"] = _offset
            resp = requests.get(
                _api("getUpdates"), params=params, timeout=request_timeout)
            resp.raise_for_status()
            data = resp.json()
            _health_update(poll_status="ok", last_poll_ok_at=time.time())
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
                                # Only ordinary messages are queued. Slash
                                # commands execute immediately, so claiming
                                # that one was queued would be a lying notice.
                                sender = message.get("from")
                                if not _wake_for_operator_message(sender):
                                    _maybe_rest_notice(chat, sender)
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
                        _tier_for_sender(sender),
                    )
        except Exception as exc:
            _health_update(force=True, poll_status="error",
                           last_poll_error_at=time.time(),
                           poll_error_type=type(exc).__name__)
            # Request exceptions can include the token-bearing API URL. Never
            # echo their full text into a persistent service journal.
            print("[telegram] poll error:", type(exc).__name__)
            time.sleep(5)


def _register_menu_commands():
    """Publish the deterministic controls to Telegram's slash-command menu."""
    try:
        response = requests.post(
            _api("setMyCommands"),
            json={
                "commands": [
                    {"command": command, "description": description}
                    for command, description in _MENU_COMMANDS
                ]
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok", False):
            raise RuntimeError("Telegram rejected the command menu")
        _health_update(force=True, menu_status="ok",
                       menu_registered_at=time.time())
    except Exception as exc:
        # Menu discoverability is not allowed to take down message polling;
        # typed slash commands continue to work and the health watch records
        # registration failures from the service journal.
        _health_update(force=True, menu_status="error",
                       menu_error_at=time.time(),
                       menu_error_type=type(exc).__name__)
        print("[telegram] command menu registration failed:",
              type(exc).__name__)


def start_telegram(token="", chat_id=""):
    global _running, _thread, _token, _allowed_chat_ids, _allow_private_chats
    global _offset_path, _log_path, _bot_username
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
    configured_username = os.environ.get(
        "METTACLAW_TELEGRAM_BOT_USERNAME", "").lstrip("@")
    if configured_username:
        _bot_username = configured_username
    if not _token:
        print("[telegram] disabled: set METTACLAW_TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN")
        return None
    if _thread and _thread.is_alive():
        return _thread
    _load_offset()
    _running = True
    _health_update(force=True, running=True, started_at=time.time(),
                   menu_status="pending", poll_status="starting")
    threading.Thread(target=_register_menu_commands, daemon=True).start()
    _thread = threading.Thread(target=_poll_loop, daemon=True)
    _thread.start()
    return _thread


def stop_telegram():
    global _running
    _running = False
    _health_update(force=True, running=False, stopped_at=time.time())


def _reply_target(chat_id=""):
    if chat_id:
        return str(chat_id)
    with _msg_lock:
        return _reply_chat_id or _last_chat_id


def _log_outbound(chat_id, text, message_id=None):
    """Record the agent's own send in the local update log so the short-term
    memory (recent_activity) shows both sides of the conversation.

    Recording `message_id` is what lets the agent later delete its own send:
    Telegram never reports a bot's outbound messages back through getUpdates,
    so if the id is not captured here it is lost, and `deleteMessage` has
    nothing to aim at. That gap is why a "clean up the test message" request
    turned into a long hunt for an id that was never stored."""
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
            "message_id": message_id,
            "text": str(text),
        }
        line = json.dumps(record, ensure_ascii=False,
                          separators=(",", ":")) + "\n"
        with _log_lock:
            with open(_log_path, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception as exc:
        print("[telegram] outbound log error:", exc)


def _log_own_delete(chat_id, message_id, note="own_delete"):
    """Tombstone one terminal deletion so cleanup never targets it again."""
    if not _log_path:
        return
    try:
        record = {
            "received_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "kind": "outbound_delete",
            "allowed": True,
            "queued": False,
            "note": note,
            "chat_id": str(chat_id),
            "from": "me",
            "from_is_bot": True,
            "message_id": int(message_id),
            "text": None,
        }
        line = json.dumps(record, ensure_ascii=False,
                          separators=(",", ":")) + "\n"
        with _log_lock:
            with open(_log_path, "a", encoding="utf-8") as f:
                f.write(line)
    except (OSError, TypeError, ValueError) as exc:
        print("[telegram] delete tombstone log error:", exc)


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
        message_id = None
        try:
            payload = resp.json()
            delivered = bool(resp.ok and payload.get("ok"))
            message_id = (payload.get("result") or {}).get("message_id")
        except ValueError:
            pass
        if delivered:
            # STM records only what Telegram actually accepted — with the id,
            # so the agent can delete its own message later.
            _log_outbound(chat_id, body, message_id)
        else:
            print(f"[telegram] send rejected (HTTP {resp.status_code})")
    except requests.exceptions.RequestException as exc:
        # A transient network failure on send must never cross Janus and kill the
        # loop (the same failure class as a provider exception crossing Janus).
        print(f"[telegram] send failed ({type(exc).__name__})")


def begin_effect_turn(turn):
    """Open the model-effect scope for one cognitive turn.

    Re-entering the same turn is deliberately a no-op: PeTTa may revisit a
    reduction while resolving later goals, but an already attempted external
    send must not become a second Telegram message.
    """
    global _effect_turn
    turn = str(turn)
    with _effect_lock:
        if turn != _effect_turn:
            _effect_turn = turn
            _effect_sends.clear()
    return turn


def send_effect_message(text, chat_id=""):
    """Attempt a model-authored Telegram send at most once in this turn."""
    target = _reply_target(chat_id)
    body = str(text).replace("\\n", "\n")
    key = (str(target), body)
    with _effect_lock:
        if key in _effect_sends:
            return "duplicate send suppressed"
        _effect_sends.add(key)
    return send_message(body, chat_id=target)


def send_effect_message_to_chat(chat_id, text):
    return send_effect_message(text, chat_id=chat_id)


def sleep_until_message(seconds):
    """Rest until the deadline or until the operator speaks or says /wake.

    A blocking sleep makes the agent unreachable for its whole duration and
    silent about it. This waits in short slices. Other senders queue without
    cutting rest short; an authenticated operator message wakes the agent and
    is consumed normally by the next turn."""
    global _sleep_until, _rest_notice_sent, _wake_reason
    try:
        seconds = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        seconds = 1
    deadline = time.time() + seconds
    # Clear a stale wake and publish the rest under the same lock used by wake
    # requests. A request is therefore ordered either before this rest or
    # after it; one published during rest cannot be lost by this clear.
    with _wake_lock:
        _wake_event.clear()
        _wake_reason = ""
        _rest_notice_sent = False
        _sleep_until = deadline
    _health_update(force=True, loop_status="waiting",
                   waiting_since=time.time(), waiting_until=deadline)
    try:
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                return "rested %ds" % seconds
            if _wake_event.wait(min(1.0, remaining)):
                with _wake_lock:
                    reason = _wake_reason or "wake request"
                return "woken by %s" % reason
    finally:
        with _wake_lock:
            _sleep_until = 0.0
            _wake_event.clear()
            _wake_reason = ""
        _health_update(force=True, loop_status="awake", waiting_until=0.0,
                       last_wait_completed_at=time.time())


def rest_status():
    """(is_resting, seconds_left) as seen from outside the sleeping loop."""
    left = _sleep_until - time.time()
    return (left > 0, math.ceil(left) if left > 0 else 0)


def send_message_to_chat(chat_id, text):
    return send_message(text, chat_id=chat_id)


def delete_message(chat_id, message_id):
    """Delete one message the bot sent. Returns a string the agent can read.

    Telegram only lets a bot delete its OWN messages, and only within 48h
    (unless it is a group admin). A forward of the bot's message counts as the
    forwarder's message, so the bot cannot delete that — the person who
    forwarded it must. The result string says which case occurred rather than
    failing silently."""
    token = _token or os.environ.get("METTACLAW_TELEGRAM_BOT_TOKEN", "")
    if not token:
        return "delete failed: no bot token configured"
    try:
        resp = requests.post(_api("deleteMessage", token),
                             json={"chat_id": str(chat_id),
                                   "message_id": int(message_id)},
                             timeout=15)
        payload = resp.json()
        if payload.get("ok"):
            _log_own_delete(chat_id, message_id)
            return "deleted message %s from chat %s" % (message_id, chat_id)
        desc = str(payload.get("description", "")).lower()
        if "can't be deleted" in desc or "message to delete not found" in desc:
            _log_own_delete(chat_id, message_id, "own_delete_terminal")
            return ("cannot delete message %s: it is older than 48h, or a "
                    "forward (whoever forwarded it must delete it), or not the "
                    "bot's own message" % message_id)
        return "delete failed: %s" % payload.get("description", resp.status_code)
    except (requests.exceptions.RequestException, ValueError, TypeError) as exc:
        return "delete failed (%s): %s" % (type(exc).__name__, exc)


def delete_my_recent(chat_id, count=1):
    """Delete the bot's own last `count` sends to a chat, newest first, using
    the ids recorded in the outbound log. This is the "clean up after a test"
    primitive: it needs no id from the operator because sends are now logged
    with their message_id. Only the bot's own recent messages are touched."""
    target = str(_reply_target(chat_id))
    ids, deleted = [], set()
    if _log_path and os.path.isfile(_log_path):
        try:
            with _log_lock:
                with open(_log_path, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            rec = json.loads(line)
                        except ValueError:
                            continue
                        if str(rec.get("chat_id")) != target:
                            continue
                        if (rec.get("note") == "own_send"
                                and rec.get("message_id")):
                            ids.append(rec["message_id"])
                        elif rec.get("note") in (
                                "own_delete", "own_delete_terminal"):
                            deleted.add(str(rec.get("message_id")))
        except OSError as exc:
            return "delete failed: cannot read outbound log: %s" % exc
    ids = [mid for mid in ids if str(mid) not in deleted]
    if not ids:
        return ("no recorded own-sends to chat %s — nothing to delete (only "
                "messages sent AFTER id-capture was added can be cleaned this "
                "way)" % target)
    try:
        n = min(20, max(1, int(count)))
    except (TypeError, ValueError):
        n = 1
    results = [delete_message(target, mid) for mid in reversed(ids[-n:])]
    return " | ".join(results)


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
                "e.g. (send-image \"/path.svg\" \"caption\" \"123456789\")")
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
        ok = False
        message_id = None
        try:
            payload = resp.json()
            ok = bool(resp.ok and payload.get("ok"))
            message_id = (payload.get("result") or {}).get("message_id")
        except ValueError:
            pass
        if not ok:
            detail = ""
            try:
                detail = ": " + str(resp.json().get("description", ""))[:160]
            except ValueError:
                pass
            return "send failed (HTTP %s)%s" % (resp.status_code, detail)
        _log_outbound(chat_id, "[%s %s] %s" % (field, os.path.basename(path),
                                               caption or ""), message_id)
        return "sent %s (%d bytes) to chat %s (msg %s)" % (
            os.path.basename(path), size, chat_id, message_id)
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
