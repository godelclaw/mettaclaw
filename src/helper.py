import hashlib
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


def working_set_save(loops, sleep, lastresults, hb_clock,
                     continuation_pending=0, banked_loops=0):
    """persist: snapshot the working self at a turn boundary.

    ``banked_loops`` is the budget a rest set aside; it belongs to the
    working self exactly like the live budget does, so a restart during a
    rest wakes owing the same energy rather than none."""
    try:
        data = _working_read()
        data.update({
            "loops": int(loops),
            "sleepInterval": int(sleep),
            "lastresults": str(lastresults)[-_WORKING_CAP:],
            "last_heartbeat": float(hb_clock),
            "continuation_pending": bool(int(continuation_pending)),
            "banked_loops": max(0, int(banked_loops)),
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



# ---- salience -------------------------------------------------------------
# An identical block reprinted every turn says nothing; the same block
# labelled "unchanged for 40 turns" is a signal — and it is exactly the
# signal that was missing on the night nothing moved. Codex diffs its
# context sections to save tokens; here the point is attention, not size.
# Held in memory only: a restart resets the streak to zero, which is honest,
# because after a boundary the agent genuinely has not been watching.

_change_marks = {}


def change_mark(name, text):
    """Return a short suffix describing how long this block has stood."""
    try:
        key = str(name)
        digest = hashlib.sha1(str(text).encode("utf-8", "replace")).hexdigest()
        previous, streak = _change_marks.get(key, (None, 0))
        if previous == digest:
            _change_marks[key] = (digest, streak + 1)
            n = streak + 1
            return " (unchanged for %d turn%s)" % (n, "" if n == 1 else "s")
        _change_marks[key] = (digest, 0)
        return "" if previous is None else " (changed)"
    except Exception:
        return ""


# ---- the running action window ------------------------------------------
# Contract (mirrors vericore's Verus heartbeat_context_policy, which solved
# this once already):
#   recent turns within limit        count <= limit
#   newest turn preserved            present -> included, always
#   no-op turns excluded             a (nop) must not consume a recency slot
#   oldest-first ordering            the window reads forwards in time
# The agent forgets what its own hands did after a single turn, which is how
# it spends bursts rediscovering files it wrote itself. This is the cheap
# half of the fix: keep the COMMANDS, drop the outputs — the outputs are
# bulky and already acted on, the commands are small and are what is missed.

_ACTION_TAIL_BYTES = 262144
_NOISE = ("(nop)", "(no_commands_parsed)", "()")


def _action_blocks(path):
    """Turn blocks from the journal, oldest last. Never raises."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - _ACTION_TAIL_BYTES))
            text = fh.read().decode("utf-8", "replace")
    except OSError:
        return []
    blocks, current = [], None
    for line in text.splitlines():
        if line.startswith('("'):
            if current is not None:
                blocks.append(current)
            current = [line]
        elif current is not None:
            current.append(line)
    if current is not None:
        blocks.append(current)
    return blocks


def _commands_of(block):
    """The command s-expression a turn issued, without the inbound message.

    A block is `<time>` then an optional `HUMAN_MESSAGE: <envelope>` then the
    response. Only the response belongs here: the message is already carried,
    in better form, by the conversation window."""
    for index, line in enumerate(block[1:], 1):
        if line.lstrip().startswith("(("):
            return "\n".join(block[index:]).strip()
    return ""


def _is_noise(commands):
    """A turn that issued nothing worth a slot in the window."""
    if not commands:
        return True
    if len(commands) < 40 and any(part in commands for part in _NOISE):
        return True
    return not commands.replace("(", "").replace(")", "").strip()


def recent_actions(path, limit=8, max_chars=12000):
    """The last `limit` substantive turns, oldest first, within max_chars.

    The newest substantive turn is never dropped: if it alone exceeds the
    budget it is truncated rather than omitted, because a window that
    silently loses the most recent action is worse than a short one."""
    try:
        limit = max(1, int(limit))
        budget = max(500, int(max_chars))
        blocks = []
        for block in _action_blocks(str(path)):
            commands = _commands_of(block)
            if not _is_noise(commands):
                blocks.append("%s %s" % (block[0].strip(), commands))
        if not blocks:
            return "(no prior actions recorded)"
        chosen, used = [], 0
        for rendered in reversed(blocks[-limit:]):
            if not chosen and len(rendered) > budget:
                rendered = rendered[:budget - 1] + "…"
            cost = len(rendered) + 2
            if chosen and used + cost > budget:
                break
            chosen.append(rendered)
            used += cost
        chosen.reverse()
        return "\n\n".join(chosen)
    except Exception as exc:
        print("[helper] recent_actions error:", type(exc).__name__, exc)
        return "(action window unavailable)"


def relevant_files(path, limit=8, max_paths=25):
    """Paths the agent has touched recently, most recent first.

    Derived from the action window rather than maintained, so it needs no
    discipline to stay true and decays on its own as actions age out."""
    try:
        window = recent_actions(path, limit=limit, max_chars=60000)
        seen = []
        pattern = r"(?<![\w/.])((?:~/|\./|/)?(?:[\w.@+-]+/)+[\w.@+-]+)"
        for match in re.finditer(pattern, window):
            candidate = match.group(1).rstrip(".,;:'\"")
            if len(candidate) < 6 or "/" not in candidate:
                continue
            if candidate in ("/dev/null", "/tmp"):
                continue
            if candidate.startswith(("http", "//")) or candidate.count("/") > 12:
                continue
            # prose is full of word/word; a path is rooted, or lives under a
            # known tree, or its last segment carries a suffix.
            rooted = candidate.startswith(("/", "./", "~/"))
            known = candidate.startswith((
                "src/", "tests/", "memory/", "channels/", "scripts/",
                "packages/", "lean/", "repos/", "docs/"))
            suffixed = "." in candidate.rsplit("/", 1)[-1]
            if not (rooted or known or suffixed):
                continue
            if candidate not in seen:
                seen.append(candidate)
        seen.reverse()
        return " ".join(seen[:max(1, int(max_paths))]) or "(none)"
    except Exception as exc:
        print("[helper] relevant_files error:", type(exc).__name__)
        return "(unavailable)"


def history_append(addition):
    """Append one internal turn to the configured conversation transcript.

    This deliberately does not share the public ``append-file`` skill.  That
    skill may stage protected source mutations; the runtime journal is an
    observation sink, not a self-modification request.  The destination is
    fixed by deployment configuration, so callers cannot turn this helper
    into general file access.
    """
    path = os.environ.get("METTACLAW_HISTORY_PATH", "./memory/history.metta")
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        payload = normalize_string(addition)
        if not payload.endswith("\n"):
            payload += "\n"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                             0o600)
        try:
            with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise
        return 1
    except Exception as exc:
        print("[helper] history append error:", type(exc).__name__)
        return 0
