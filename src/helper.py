import os
import re


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


def strip_trailing_affect(value):
    # Drop only a complete final affect-trace line. A diamond in prose, string
    # data, or code is ordinary content and must reach the command parser.
    text = str(value)
    lines = text.splitlines(keepends=True)
    if not lines:
        return text

    final = lines[-1]
    final_without_eol = final.rstrip("\r\n")
    if final_without_eol.startswith("⋄⟨") and final_without_eol.endswith("⟩"):
        return "".join(lines[:-1])
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


def recycle_requested():
    """Return PeTTa's integer truth value for the boundary flag."""
    path = os.environ.get("METTACLAW_RECYCLE_REQUEST_PATH", "")
    return 1 if path and os.path.isfile(path) else 0


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
