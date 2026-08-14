import json
import os
import re
import sys
import time
import hashlib


SAFE_TEXT_REPLACEMENTS = (
    ("_newline_", "\n"),
    ("_quote_", '"'),
    ("_apostrophe_", "'"),
)

_SOURCE_REVISION = None
_RUNTIME_SOURCES = (
    "src/agent_kernel.py",
    "src/attention_graph.metta",
    "src/loop_modes.py",
    "src/loop.metta",
    "src/skills.pl",
    "src/channels.metta",
    "channels/telegram.py",
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


def _source_revision():
    global _SOURCE_REVISION
    configured = os.environ.get("METTACLAW_RUNTIME_REVISION", "").strip()
    if configured:
        return configured
    if _SOURCE_REVISION is not None:
        return _SOURCE_REVISION
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    hasher = hashlib.sha256()
    for relative in _RUNTIME_SOURCES:
        hasher.update(relative.encode("utf-8") + b"\0")
        try:
            with open(os.path.join(root, relative), "rb") as stream:
                for block in iter(lambda: stream.read(65536), b""):
                    hasher.update(block)
        except OSError:
            hasher.update(b"<missing>")
    _SOURCE_REVISION = hasher.hexdigest()
    return _SOURCE_REVISION


def controller_revision(mode, model, engine):
    """Stable identity of the policy, model, engine, and running source."""
    return _agent_kernel().digest({
        "mode": str(mode),
        "model": str(model),
        "engine": str(engine),
        "source": _source_revision(),
    })


def current_controller_revision():
    """Compute controller identity from live policy selectors."""
    import engine_modes
    import loop_modes
    import synthetic_llm
    return controller_revision(
        loop_modes.current_mode(),
        synthetic_llm.current_model(),
        engine_modes.active_engine(),
    )


def receipt_current(receipt_id):
    """Recheck against live controller state, never a caller's old token."""
    return _agent_kernel().receipt_current(
        receipt_id, current_controller_revision())


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


def _recycle_safe_path():
    configured = os.environ.get("METTACLAW_RECYCLE_SAFE_PATH", "")
    if configured:
        return configured
    request = os.environ.get("METTACLAW_RECYCLE_REQUEST_PATH", "")
    return request + ".safe" if request else ""


def recycle_ack():
    """Consume the boundary flag: the NEW process clears it at boot, so a
    pending request can fire at most one process exit. Before this
    existed, the flag was immortal — nothing anywhere removed it."""
    paths = (os.environ.get("METTACLAW_RECYCLE_REQUEST_PATH", ""),
             _recycle_safe_path())
    for path in paths:
        try:
            if path and os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass
    return 1


def _recycle_mark_safe():
    """Publish that the current kernel reached a persisted turn boundary."""
    request = os.environ.get("METTACLAW_RECYCLE_REQUEST_PATH", "")
    path = _recycle_safe_path()
    if not request or not os.path.isfile(request) or not path:
        return 0
    parent = os.path.dirname(path) or "."
    temporary = "%s.tmp.%d" % (path, os.getpid())
    try:
        os.makedirs(parent, exist_ok=True)
        with open(temporary, "w", encoding="utf-8") as stream:
            stream.write("safely_wrapped_up=%.6f pid=%d\n" %
                         (time.time(), os.getpid()))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        try:
            directory = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError:
            pass
        return 1
    except OSError as exc:
        try:
            os.remove(temporary)
        except OSError:
            pass
        print("[recycle] safe-boundary receipt failed:", type(exc).__name__)
        return 0


def recycle_exit(persisted=0):
    """Hard process exit for the recycle boundary. Merely returning from
    the loop recursion lands in engine backtracking, which re-enters the
    loop from scratch inside the same process — a boot-loop that re-arms
    a fresh budget every cycle (the 2026-08-06 storm). The service
    manager (Restart=always) starts the fresh heap. A successful working-set
    snapshot earns a durable receipt that permits an immediate relaunch."""
    try:
        boundary_is_safe = int(persisted) == 1
    except (TypeError, ValueError):
        boundary_is_safe = False
    if boundary_is_safe:
        _recycle_mark_safe()
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


def _agent_kernel():
    try:
        import agent_kernel
    except ImportError:
        from src import agent_kernel
    return agent_kernel


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


def _record_working_set(data):
    """Mirror the capsule into the causal ledger without risking continuity."""
    try:
        _agent_kernel().record_working_set(data)
        return True
    except Exception as exc:
        print("[agent-kernel] working-set record failed:", type(exc).__name__)
        return False


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
        _record_working_set(data)
        return 1
    except Exception:
        return 0


def intent_save(why):
    """Store the agent's stated rest intention; it greets the next
    waking (WOKE_FROM_REST) and survives any boundary in between."""
    try:
        data = _working_read()
        data["intent"] = str(why)[:500]
        data["saved_at"] = time.time()
        _working_write(data)
        _record_working_set(data)
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
    try:
        logged = _agent_kernel().latest_working_set()
        if logged and (
                not data
                or float(logged.get("saved_at", 0))
                > float(data.get("saved_at", 0))):
            data = logged
    except Exception as exc:
        # Keep the last-known-good capsule alive when the ledger is unavailable
        # or corrupt; the infrastructure failure remains observable.
        print("[agent-kernel] working-set replay failed:", type(exc).__name__)
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
                data["saved_at"] = time.time()
                _working_write(data)  # consume the intention on disk
                _record_working_set(data)
            except Exception:
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
