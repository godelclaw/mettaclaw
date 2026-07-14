from dataclasses import dataclass
from enum import Enum
import re


MAX_ACTIONS = 5
MAX_INPUT_BYTES = 65536
MAX_NESTING = 4096


class WireErrorCode(str, Enum):
    INPUT_TOO_LARGE = "InputTooLarge"
    UNSUPPORTED_BOM = "UnsupportedBom"
    NO_ACTIONS = "NoActions"
    SYNTAX = "Syntax"
    TOO_MANY_ACTIONS = "TooManyActions"
    ACTION_NOT_EXPRESSION = "ActionNotExpression"
    INVALID_ACTION_HEAD = "InvalidActionHead"
    INVALID_AFFECT = "InvalidAffect"
    DUPLICATE_AFFECT = "DuplicateAffect"


class WireError(ValueError):
    def __init__(self, code, offset, action_index=0):
        self.code = WireErrorCode(code)
        self.offset = int(offset)
        self.action_index = int(action_index)
        super().__init__(f"{self.code.value} at byte {self.offset}")


@dataclass(frozen=True)
class DecodedTurn:
    actions: tuple[str, ...]
    affect: str | None = None
    encoding: str = "sexpr-sequence"

    def as_legacy_list(self):
        return "(" + " ".join(self.actions) + ")"


_AFFECT_VALUE = r"[-+]?(?:1(?:\.0*)?|0?(?:\.\d+))"
_AFFECT_BODY = (
    rf"Cn:{_AFFECT_VALUE}[ \t]+C:{_AFFECT_VALUE}[ \t]+"
    rf"Ct:{_AFFECT_VALUE}[ \t]+I:{_AFFECT_VALUE}[ \t]+"
    rf"J:{_AFFECT_VALUE}[ \t]+A:{_AFFECT_VALUE}[ \t]+"
    rf"S:{_AFFECT_VALUE}[ \t]+Co:{_AFFECT_VALUE}"
)
_UNICODE_AFFECT = re.compile(rf"^⋄⟨{_AFFECT_BODY}⟩$")
_ASCII_AFFECT = re.compile(rf"^\[{_AFFECT_BODY}\]$")


def _byte_offset(text, char_offset):
    return len(text[:char_offset].encode("utf-8"))


def _error(text, code, char_offset, action_index=0):
    raise WireError(code, _byte_offset(text, char_offset), action_index)


def _skip_layout(text, offset, stop=None):
    stop = len(text) if stop is None else stop
    while offset < stop:
        if text[offset].isspace():
            offset += 1
            continue
        if text[offset] == ";":
            newline = text.find("\n", offset + 1, stop)
            offset = stop if newline < 0 else newline + 1
            continue
        break
    return offset


def _read_expression(text, offset, action_index, stop=None):
    stop = len(text) if stop is None else stop
    if offset >= stop or text[offset] != "(":
        _error(text, WireErrorCode.ACTION_NOT_EXPRESSION, offset, action_index)

    depth = 0
    in_string = False
    escaped = False
    i = offset
    while i < stop:
        char = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            i += 1
            continue
        if char == '"':
            in_string = True
        elif char == ";":
            newline = text.find("\n", i + 1, stop)
            i = stop if newline < 0 else newline + 1
            continue
        elif char == "(":
            depth += 1
            if depth > MAX_NESTING:
                _error(text, WireErrorCode.SYNTAX, i, action_index)
        elif char == ")":
            depth -= 1
            if depth == 0:
                return i + 1
            if depth < 0:
                _error(text, WireErrorCode.SYNTAX, i, action_index)
        i += 1
    _error(text, WireErrorCode.SYNTAX, stop, action_index)


def _validate_action_head(text, start, end, action_index):
    head = _skip_layout(text, start + 1, end - 1)
    if head >= end - 1 or text[head] in {'"', "(", ")", "$"}:
        _error(text, WireErrorCode.INVALID_ACTION_HEAD, head, action_index)
    token_end = head
    while token_end < end - 1:
        char = text[token_end]
        if char.isspace() or char in "();":
            break
        token_end += 1
    if token_end == head:
        _error(text, WireErrorCode.INVALID_ACTION_HEAD, head, action_index)


def _is_affect_line(value):
    return bool(_UNICODE_AFFECT.fullmatch(value) or _ASCII_AFFECT.fullmatch(value))


def _read_affect(text, offset, action_index):
    tail = text[offset:].strip()
    lines = [line.strip() for line in tail.splitlines() if line.strip()]
    if len(lines) > 1 and all(_is_affect_line(line) for line in lines):
        _error(text, WireErrorCode.DUPLICATE_AFFECT, offset, action_index)
    if len(lines) != 1 or not _is_affect_line(lines[0]):
        _error(text, WireErrorCode.INVALID_AFFECT, offset, action_index)
    return lines[0]


def _read_sequence(text, start=0, stop=None, allow_outer_list=False):
    stop = len(text) if stop is None else stop
    actions = []
    spans = []
    affect = None
    offset = start
    while True:
        offset = _skip_layout(text, offset, stop)
        if offset >= stop:
            break
        if text.startswith("⋄⟨", offset) or text[offset] == "[":
            affect = _read_affect(text[:stop], offset, len(actions))
            offset = stop
            break
        if text[offset] != "(":
            _error(text, WireErrorCode.ACTION_NOT_EXPRESSION, offset, len(actions))
        end = _read_expression(text, offset, len(actions), stop)
        head = _skip_layout(text, offset + 1, end - 1)
        outer_list_shape = (
            allow_outer_list
            and not actions
            and (head >= end - 1 or text[head] == "(")
        )
        if not outer_list_shape:
            _validate_action_head(text, offset, end, len(actions))
        actions.append(text[offset:end].strip())
        spans.append((offset, end))
        if len(actions) > MAX_ACTIONS:
            _error(text, WireErrorCode.TOO_MANY_ACTIONS, offset, len(actions) - 1)
        offset = end
    return actions, spans, affect


def decode_sexpr_output(value):
    text = str(value)
    if len(text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise WireError(WireErrorCode.INPUT_TOO_LARGE, MAX_INPUT_BYTES, 0)
    if text.startswith("\ufeff"):
        raise WireError(WireErrorCode.UNSUPPORTED_BOM, 0, 0)

    actions, spans, affect = _read_sequence(text, allow_outer_list=True)
    encoding = "sexpr-sequence"

    # During migration, accept one outer list of actions but never emit it as
    # the canonical wire representation.
    if len(actions) == 1 and affect is None:
        start, end = spans[0]
        inner = _skip_layout(text, start + 1, end - 1)
        if inner >= end - 1:
            actions = []
            encoding = "legacy-sexpr-list"
        elif text[inner] == "(":
            actions, _, inner_affect = _read_sequence(text, start + 1, end - 1)
            if inner_affect is not None:
                _error(text, WireErrorCode.INVALID_AFFECT, inner, 0)
            encoding = "legacy-sexpr-list"

    if not actions:
        raise WireError(WireErrorCode.NO_ACTIONS, len(text.encode("utf-8")), 0)
    if len(actions) > MAX_ACTIONS:
        raise WireError(WireErrorCode.TOO_MANY_ACTIONS, 0, MAX_ACTIONS)
    return DecodedTurn(tuple(actions), affect, encoding)
