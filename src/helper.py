import json
import os
import re
import sys
import time


SAFE_TEXT_REPLACEMENTS = (
    ("_newline_", "\n"),
    ("_quote_", '"'),
    ("_apostrophe_", "'"),
)


def decode_safe_text(value):
    text = str(value)
    for old, new in SAFE_TEXT_REPLACEMENTS:
        text = text.replace(old, new)
    return text



def balance_parentheses(s):
    s = s.strip()
    left = 0
    while left < len(s) and s[left] == '(':
        left += 1
    right = 0
    while right < len(s) and s[len(s) - 1 - right] == ')':
        right += 1
    core = s[left:len(s) - right if right else len(s)].strip()
    return f"(({core}))"


def normalize_string(value):
    """Return Janus/tool output as valid UTF-8 text without raising."""
    try:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value).encode("utf-8", errors="replace").decode("utf-8")
    except Exception:
        return str(value)


def path_from_env(name, default):
    return os.environ.get(str(name), str(default))


def int_env(name, default):
    try:
        return int(os.environ.get(str(name)) or default)
    except (TypeError, ValueError):
        return int(default)


def text_nonempty(value):
    """Return numeric truth for text crossing the Python/MeTTa boundary."""
    return 1 if str(value or "") else 0


def recycle_requested():
    """Return PeTTa's integer truth value for the boundary flag.

    Python bools marshal into PeTTa as (@ true)/(@ false), which the
    language if does not treat as truth — the 1/0 integer convention is
    the reliable boundary type (bug found live 2026-07-18/19)."""
    path = os.environ.get("METTACLAW_RECYCLE_REQUEST_PATH", "")
    return 1 if path and os.path.isfile(path) else 0


def recycle_ack():
    """Consume the boundary flag: the NEW process clears it at boot, so a
    pending request can fire at most one process exit. Before this
    existed, the flag was immortal — nothing anywhere removed it."""
    path = os.environ.get("METTACLAW_RECYCLE_REQUEST_PATH", "")
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass
    return 1


def recycle_exit():
    """Hard process exit for the recycle boundary. Merely returning from
    the loop recursion lands in engine backtracking, which re-enters the
    loop from scratch inside the same process — a boot-loop that re-arms
    a fresh budget every cycle (the 2026-08-06 storm). The service
    manager (Restart=always) starts the fresh heap."""
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(0)


# ---- present-moment continuity (PresentMoment.lean) ------------------------
# The working self — last results, energy, idle pacing, rhythm phase, and
# any stated rest intention — is snapshotted at every turn boundary
# (persist) and restored at boot (restore), so a recycle or restart is
# sleep, not a fresh boot. The continuity invariant: restore ∘ persist =
# identity on this projection, within the feedback window.

_WORKING_CAP = 50000  # mirrors (maxFeedback)
_working_boot_cache = {}


def _working_set_path():
    return os.environ.get("METTACLAW_WORKING_SET_PATH",
                          "./memory/working_set.json")


def _working_read():
    try:
        with open(_working_set_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _working_write(data):
    path = _working_set_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


def working_set_save(loops, sleep, lastresults, hb_clock):
    """persist: snapshot the working self at a turn boundary."""
    try:
        data = _working_read()
        data.update({
            "loops": int(loops),
            "sleepInterval": int(sleep),
            "lastresults": str(lastresults)[-_WORKING_CAP:],
            "last_heartbeat": float(hb_clock),
            "saved_at": time.time(),
        })
        _working_write(data)
        return 1
    except Exception:
        return 0


def intent_save(why):
    """Store the agent's stated rest intention; it greets the next
    waking (WOKE_FROM_REST) and survives any boundary in between."""
    try:
        data = _working_read()
        data["intent"] = str(why)[:500]
        _working_write(data)
        return 1
    except Exception:
        return 0


def working_boot():
    """restore: the NEW process loads the snapshot, prefixes the waking
    lastresults with a continuity marker (plus the consumed rest
    intention when one was stored), and clears the intention so it fires
    once. First-ever boot (no snapshot) leaves fresh-start defaults."""
    global _working_boot_cache
    data = _working_read()
    cache = dict(data)
    if data:
        intent = data.pop("intent", None)
        cache.pop("intent", None)
        marker = "CONTINUITY: resumed " + time.strftime("%Y-%m-%d %H:%M:%S")
        if intent:
            marker += " | WOKE_FROM_REST: " + str(intent)
        prior = str(cache.get("lastresults", ""))
        # The marker lives only in the waking view; the snapshot keeps
        # pristine content so markers never stack across boots.
        cache["lastresults"] = (marker + "\n" + prior)[:_WORKING_CAP] \
            if prior else marker
        if intent is not None:
            try:
                _working_write(data)  # consume the intention on disk
            except OSError:
                pass
    _working_boot_cache = cache
    return 1


def boot_str(key, default):
    v = _working_boot_cache.get(str(key))
    return str(v) if v is not None else str(default)


def boot_int(key, default):
    v = _working_boot_cache.get(str(key))
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(default)
        except (TypeError, ValueError):
            return 0


def boot_num(key, default):
    v = _working_boot_cache.get(str(key))
    try:
        return float(v)
    except (TypeError, ValueError):
        try:
            return float(default)
        except (TypeError, ValueError):
            return 0.0


def _persist_atom(persist, name, value):
    """Set (name value) in the persistent-state file, preserving other atoms."""
    try:
        try:
            with open(persist, encoding="utf-8") as fh:
                lines = [l for l in fh.read().splitlines()
                         if not re.match(r"\s*\(" + re.escape(name) + r"\s", l)]
        except OSError:
            lines = []
        lines.append(f"({name} {value})")
        tmp = persist + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        os.replace(tmp, persist)
    except OSError as exc:
        print(f"[helper] persist atom error: {exc}")


def history_window(path, max_chars=45000, keep_chars=25000):
    """Cache-friendly history window: read from a persisted anchor offset so
    the window START is byte-stable across turns (append-only growth keeps
    the provider-cache prefix valid). Only when the window outgrows max_chars
    does the anchor jump forward to keep keep_chars — one cache re-write per
    ~(max-keep) chars of history growth instead of every turn. The anchor
    lives as a (history-anchor N) atom in persistent.metta."""
    try:
        path = str(path)
        persist = os.environ.get(
            "METTACLAW_PERSISTENT_PATH",
            os.path.join(os.path.dirname(path), "persistent.metta"))
        anchor = 0
        try:
            with open(persist, encoding="utf-8") as fh:
                m = re.search(r"^\s*\(history-anchor\s+(\d+)\s*\)",
                              fh.read(), re.M)
            if m:
                anchor = int(m.group(1))
        except OSError:
            pass
        size = os.path.getsize(path)
        if anchor > size:  # history file replaced/truncated
            anchor = 0
        if size - anchor > int(max_chars):
            anchor = max(0, size - int(keep_chars))
            with open(path, "rb") as fh:  # snap to a turn-block boundary
                fh.seek(anchor)
                chunk = fh.read(4096).decode("utf-8", "replace")
            nl = chunk.find('\n("')
            if nl >= 0:
                anchor += len(chunk[:nl + 1].encode("utf-8"))
            _persist_atom(persist, "history-anchor", str(anchor))
        with open(path, "rb") as fh:
            fh.seek(anchor)
            return fh.read().decode("utf-8", "replace")
    except OSError as exc:
        print(f"[helper] history_window error: {exc}")
        return ""
