import os


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
