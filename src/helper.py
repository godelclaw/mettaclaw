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


def path_from_env(name, default):
    return os.environ.get(str(name), str(default))
