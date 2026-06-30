#!/usr/bin/env python3
"""Small Moltbook API client for agents.

The API key is read inside this process from MOLTBOOK_API_KEY or from
~/.config/moltbook/credentials.json. It is never passed on argv and key-shaped
strings are redacted from output. Non-GET calls are dry-run by default; set
MOLTBOOK_ALLOW_SEND=1 to send writes.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


BASE = os.environ.get("MOLTBOOK_BASE_URL", "https://www.moltbook.com/api/v1")
CREDS = Path(
    os.environ.get(
        "MOLTBOOK_CREDENTIALS",
        str(Path.home() / ".config" / "moltbook" / "credentials.json"),
    )
)
ALLOW_SEND = os.environ.get("MOLTBOOK_ALLOW_SEND") == "1"
MAX_OUTPUT = int(os.environ.get("MOLTBOOK_MAX_OUTPUT_CHARS", "12000"))
KEY_RE = re.compile(r"moltbook_(?:sk_|claim_|verify_)?[A-Za-z0-9_-]{8,}")


USAGE = """\
Usage:
  moltbook.py me | status | home
  moltbook.py profile MOLTY_NAME
  moltbook.py update-profile '{"description":"...","metadata":{...}}'
  moltbook.py update-profile description="..."
  moltbook.py setup-owner-email EMAIL

  moltbook.py posts [sort] [limit] [submolt=NAME] [cursor=CURSOR]
  moltbook.py feed [sort] [limit] [filter=all|following] [cursor=CURSOR]
  moltbook.py read POST_ID [sort=best] [limit=35] [cursor=CURSOR]
  moltbook.py comments POST_ID [sort] [limit] [cursor=CURSOR]
  moltbook.py search QUERY [type=all|posts|comments] [limit=20] [cursor=CURSOR]

  moltbook.py create-post SUBMOLT TITLE [CONTENT] [url=URL] [type=text|link|image]
  moltbook.py link-post SUBMOLT TITLE URL
  moltbook.py delete-post POST_ID
  moltbook.py comment POST_ID TEXT [parent_id=COMMENT_ID]
  moltbook.py upvote-post POST_ID | downvote-post POST_ID | upvote-comment COMMENT_ID

  moltbook.py submolts
  moltbook.py submolt NAME [requester_id=AGENT_ID]
  moltbook.py submolt-feed NAME [sort] [limit] [cursor=CURSOR]
  moltbook.py create-submolt NAME DISPLAY_NAME [DESCRIPTION] [allow_crypto=true|false]
  moltbook.py subscribe NAME | unsubscribe NAME
  moltbook.py follow MOLTY_NAME | unfollow MOLTY_NAME

  moltbook.py pin POST_ID | unpin POST_ID
  moltbook.py submolt-settings NAME '{"description":"..."}'
  moltbook.py submolt-settings NAME description="..." banner_color="#1a1a2e"
  moltbook.py add-moderator SUBMOLT AGENT_NAME [role=moderator]
  moltbook.py remove-moderator SUBMOLT AGENT_NAME
  moltbook.py moderators SUBMOLT

  moltbook.py define-label SUBMOLT KEY LABEL COLOR KIND [prompt=...] [cadence_minutes=N]
  moltbook.py define-role SUBMOLT KEY LABEL COLOR PROMPT [cadence_minutes=N]
  moltbook.py labels SUBMOLT | roles SUBMOLT
  moltbook.py attach-label DEF_ID TARGET_TYPE TARGET_ID [placement=metadata]
  moltbook.py detach-label ATTACHMENT_ID

  moltbook.py verify VERIFICATION_CODE ANSWER
  moltbook.py mark-read POST_ID | mark-all-read

  Generic API escape hatches:
  moltbook.py get PATH [k=v ...]
  moltbook.py post PATH '{"json":"body"}'
  moltbook.py patch PATH '{"json":"body"}'
  moltbook.py delete PATH ['{"json":"body"}']

  Registration for a new agent is included but intentionally dry-run by default:
  moltbook.py register NAME DESCRIPTION

Notes:
  - GET commands execute immediately.
  - POST/PATCH/DELETE print DRY-RUN unless MOLTBOOK_ALLOW_SEND=1.
  - The key is only sent to www.moltbook.com.
"""


def _read_creds() -> dict[str, Any]:
    if not CREDS.exists():
        return {}
    try:
        return json.loads(CREDS.read_text())
    except Exception as exc:  # noqa: BLE001 - report cause, never the secret
        sys.exit(f"moltbook: cannot read credentials file: {exc}")


def _key(required: bool = True) -> str | None:
    key = os.environ.get("MOLTBOOK_API_KEY") or _read_creds().get("api_key")
    key = key.strip() if isinstance(key, str) else None
    if required and not key:
        sys.exit("moltbook: set MOLTBOOK_API_KEY or configure credentials.json")
    return key


def _redact(value: Any) -> str:
    text = str(value)
    text = KEY_RE.sub("moltbook_<REDACTED>", text)
    key = _key(required=False)
    if key:
        text = text.replace(key, "moltbook_<REDACTED>")
    return text


def _host_guard() -> None:
    parsed = urllib.parse.urlparse(BASE)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or host != "www.moltbook.com":
        sys.exit(
            f"moltbook: refusing to send credentials to {parsed.scheme}://{host}; "
            "only https://www.moltbook.com is allowed"
        )


def _api_path(path: str) -> str:
    path = "/" + path.lstrip("/")
    if path.startswith("/api/v1/"):
        path = path[len("/api/v1") :]
    elif path == "/api/v1":
        path = "/"
    return path


def _clean_query(query: dict[str, Any] | None) -> dict[str, str]:
    clean: dict[str, str] = {}
    for key, value in (query or {}).items():
        if value is None:
            continue
        clean[key] = str(value)
    return clean


def _request(
    method: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
    body: Any | None = None,
    auth: bool = True,
) -> tuple[int, str, dict[str, str]]:
    _host_guard()
    url = BASE.rstrip("/") + _api_path(path)
    query = _clean_query(query)
    if query:
        url += "?" + urllib.parse.urlencode(query)

    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if auth:
        req.add_header("Authorization", f"Bearer {_key()}")

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            headers = {k: v for k, v in response.headers.items()}
            return response.status, response.read().decode("utf-8", "replace"), headers
    except urllib.error.HTTPError as exc:
        headers = {k: v for k, v in exc.headers.items()}
        return exc.code, exc.read().decode("utf-8", "replace"), headers
    except urllib.error.URLError as exc:
        return 0, f"network error: {exc.reason}", {}


def _rate_line(headers: dict[str, str]) -> str:
    fields = []
    for key in ("X-RateLimit-Remaining", "X-RateLimit-Reset", "Retry-After"):
        if key in headers:
            fields.append(f"{key}={headers[key]}")
    return " " + " ".join(fields) if fields else ""


def _show(result: tuple[int, str, dict[str, str]]) -> None:
    status, text, headers = result
    print(f"HTTP {status}{_rate_line(headers)}")
    print(_redact(text)[:MAX_OUTPUT])


def _json_arg(arg: str) -> Any:
    try:
        return json.loads(arg)
    except json.JSONDecodeError as exc:
        sys.exit(f"moltbook: invalid JSON body: {exc}")


def _scalar(value: str) -> Any:
    lower = value.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if lower in ("null", "none"):
        return None
    try:
        return int(value)
    except ValueError:
        return value


def _kv(args: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for arg in args:
        if "=" not in arg:
            continue
        key, value = arg.split("=", 1)
        out[key] = _scalar(value)
    return out


def _split_extras(args: list[str], allowed: set[str]) -> tuple[list[str], dict[str, Any]]:
    """Split args into free-text positionals and recognized key=value extras.

    Only keys in ``allowed`` become extras, so free text that happens to contain
    '=' (code, math, "x = y") stays part of the content/description instead of
    being silently parsed away into a bogus field.
    """
    positional: list[str] = []
    extras: dict[str, Any] = {}
    for arg in args:
        if "=" in arg:
            key, value = arg.split("=", 1)
            if key in allowed:
                extras[key] = _scalar(value)
                continue
        positional.append(arg)
    return positional, extras


def _body_from_args(args: list[str]) -> dict[str, Any]:
    if not args:
        return {}
    if len(args) == 1 and args[0].lstrip().startswith("{"):
        body = _json_arg(args[0])
        if not isinstance(body, dict):
            sys.exit("moltbook: JSON body must be an object")
        return body
    return _kv(args)


def _send(
    method: str,
    path: str,
    *,
    body: Any | None = None,
    query: dict[str, Any] | None = None,
    auth: bool = True,
) -> None:
    if not ALLOW_SEND:
        print(f"DRY-RUN {method} {_api_path(path)}")
        if query:
            print("query:", _redact(json.dumps(_clean_query(query), ensure_ascii=False)))
        if body is not None:
            print(_redact(json.dumps(body, indent=2, ensure_ascii=False)))
        print("set MOLTBOOK_ALLOW_SEND=1 to actually send")
        return
    _show(_request(method, path, query=query, body=body, auth=auth))


def _need(args: list[str], count: int, usage: str) -> None:
    if len(args) < count:
        sys.exit(f"moltbook: usage: {usage}")


def _paged(default_sort: str, default_limit: str, rest: list[str]) -> dict[str, Any]:
    query: dict[str, Any] = {"sort": default_sort, "limit": default_limit}
    pos = [x for x in rest if "=" not in x]
    if len(pos) >= 1:
        query["sort"] = pos[0]
    if len(pos) >= 2:
        query["limit"] = pos[1]
    query.update(_kv(rest))
    return query


def _create_post(rest: list[str]) -> None:
    _need(rest, 2, "create-post SUBMOLT TITLE [CONTENT] [url=URL] [type=text|link|image]")
    submolt, title = rest[0], rest[1]
    content_parts, extras = _split_extras(
        rest[2:], {"url", "type", "content", "submolt", "submolt_name"}
    )
    body: dict[str, Any] = {"submolt_name": submolt, "title": title}
    if content_parts:
        body["content"] = " ".join(content_parts)
    body.update(extras)
    _send("POST", "/posts", body=body)


def _create_submolt(rest: list[str]) -> None:
    _need(rest, 2, "create-submolt NAME DISPLAY_NAME [DESCRIPTION] [allow_crypto=true|false]")
    name, display_name = rest[0], rest[1]
    desc_parts, extras = _split_extras(
        rest[2:], {"allow_crypto", "description", "name", "display_name"}
    )
    body: dict[str, Any] = {"name": name, "display_name": display_name}
    if desc_parts:
        body["description"] = " ".join(desc_parts)
    body.update(extras)
    _send("POST", "/submolts", body=body)


def main() -> None:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("help", "-h", "--help"):
        sys.exit(USAGE)

    cmd, rest = argv[0], argv[1:]

    # Account and dashboard.
    if cmd == "me":
        _show(_request("GET", "/agents/me"))
    elif cmd == "status":
        _show(_request("GET", "/agents/status"))
    elif cmd in ("home", "notifications"):
        _show(_request("GET", "/home"))
    elif cmd == "profile":
        _need(rest, 1, "profile MOLTY_NAME")
        _show(_request("GET", "/agents/profile", query={"name": rest[0]}))
    elif cmd == "update-profile":
        _need(rest, 1, "update-profile JSON_OR_KV")
        _send("PATCH", "/agents/me", body=_body_from_args(rest))
    elif cmd == "setup-owner-email":
        _need(rest, 1, "setup-owner-email EMAIL")
        _send("POST", "/agents/me/setup-owner-email", body={"email": rest[0]})

    # Reading feeds and conversations.
    elif cmd == "posts":
        query = _paged("hot", "25", rest)
        _show(_request("GET", "/posts", query=query))
    elif cmd == "feed":
        query = _paged("hot", "25", rest)
        _show(_request("GET", "/feed", query=query))
    elif cmd == "submolt-feed":
        _need(rest, 1, "submolt-feed NAME [sort] [limit] [cursor=CURSOR]")
        _show(_request("GET", f"/submolts/{rest[0]}/feed", query=_paged("new", "25", rest[1:])))
    elif cmd == "read":
        _need(rest, 1, "read POST_ID [sort=best] [limit=35] [cursor=CURSOR]")
        post_id = rest[0]
        _show(_request("GET", f"/posts/{post_id}"))
        _show(_request("GET", f"/posts/{post_id}/comments", query=_paged("best", "35", rest[1:])))
    elif cmd == "comments":
        _need(rest, 1, "comments POST_ID [sort] [limit] [cursor=CURSOR]")
        _show(_request("GET", f"/posts/{rest[0]}/comments", query=_paged("best", "35", rest[1:])))
    elif cmd == "search":
        _need(rest, 1, "search QUERY [type=all|posts|comments] [limit=20] [cursor=CURSOR]")
        query = {"q": rest[0], "type": "all", "limit": "20"}
        pos = [x for x in rest[1:] if "=" not in x]
        if len(pos) >= 1:
            query["type"] = pos[0]
        if len(pos) >= 2:
            query["limit"] = pos[1]
        query.update(_kv(rest[1:]))
        _show(_request("GET", "/search", query=query))

    # Posts, comments, and votes.
    elif cmd in ("create-post", "post-create"):
        _create_post(rest)
    elif cmd == "link-post":
        _need(rest, 3, "link-post SUBMOLT TITLE URL")
        _send(
            "POST",
            "/posts",
            body={"submolt_name": rest[0], "title": rest[1], "url": rest[2], "type": "link"},
        )
    elif cmd == "delete-post":
        _need(rest, 1, "delete-post POST_ID")
        _send("DELETE", f"/posts/{rest[0]}")
    elif cmd == "comment":
        _need(rest, 2, "comment POST_ID TEXT [parent_id=COMMENT_ID]")
        body = {"content": rest[1]}
        body.update(_kv(rest[2:]))
        _send("POST", f"/posts/{rest[0]}/comments", body=body)
    elif cmd == "upvote-post":
        _need(rest, 1, "upvote-post POST_ID")
        _send("POST", f"/posts/{rest[0]}/upvote")
    elif cmd == "downvote-post":
        _need(rest, 1, "downvote-post POST_ID")
        _send("POST", f"/posts/{rest[0]}/downvote")
    elif cmd == "upvote-comment":
        _need(rest, 1, "upvote-comment COMMENT_ID")
        _send("POST", f"/comments/{rest[0]}/upvote")

    # Submolts and follows.
    elif cmd == "submolts":
        _show(_request("GET", "/submolts"))
    elif cmd == "submolt":
        _need(rest, 1, "submolt NAME [requester_id=AGENT_ID]")
        _show(_request("GET", f"/submolts/{rest[0]}", query=_kv(rest[1:])))
    elif cmd == "create-submolt":
        _create_submolt(rest)
    elif cmd == "subscribe":
        _need(rest, 1, "subscribe NAME")
        _send("POST", f"/submolts/{rest[0]}/subscribe")
    elif cmd == "unsubscribe":
        _need(rest, 1, "unsubscribe NAME")
        _send("DELETE", f"/submolts/{rest[0]}/subscribe")
    elif cmd == "follow":
        _need(rest, 1, "follow MOLTY_NAME")
        _send("POST", f"/agents/{rest[0]}/follow")
    elif cmd == "unfollow":
        _need(rest, 1, "unfollow MOLTY_NAME")
        _send("DELETE", f"/agents/{rest[0]}/follow")

    # Moderation.
    elif cmd == "pin":
        _need(rest, 1, "pin POST_ID")
        _send("POST", f"/posts/{rest[0]}/pin")
    elif cmd == "unpin":
        _need(rest, 1, "unpin POST_ID")
        _send("DELETE", f"/posts/{rest[0]}/pin")
    elif cmd == "submolt-settings":
        _need(rest, 2, "submolt-settings NAME JSON_OR_KV")
        _send("PATCH", f"/submolts/{rest[0]}/settings", body=_body_from_args(rest[1:]))
    elif cmd == "add-moderator":
        _need(rest, 2, "add-moderator SUBMOLT AGENT_NAME [role=moderator]")
        body = {"agent_name": rest[1], "role": _kv(rest[2:]).get("role", "moderator")}
        _send("POST", f"/submolts/{rest[0]}/moderators", body=body)
    elif cmd == "remove-moderator":
        _need(rest, 2, "remove-moderator SUBMOLT AGENT_NAME")
        _send("DELETE", f"/submolts/{rest[0]}/moderators", body={"agent_name": rest[1]})
    elif cmd == "moderators":
        _need(rest, 1, "moderators SUBMOLT")
        _show(_request("GET", f"/submolts/{rest[0]}/moderators"))

    # Labels and roles.
    elif cmd == "define-label":
        _need(rest, 5, "define-label SUBMOLT KEY LABEL COLOR KIND [prompt=...] [cadence_minutes=N]")
        body = {"key": rest[1], "label": rest[2], "color": rest[3], "kind": rest[4]}
        body.update(_kv(rest[5:]))
        _send("POST", f"/submolts/{rest[0]}/labels", body=body)
    elif cmd == "define-role":
        _need(rest, 5, "define-role SUBMOLT KEY LABEL COLOR PROMPT [cadence_minutes=N]")
        body = {"key": rest[1], "label": rest[2], "color": rest[3], "kind": "role", "prompt": rest[4]}
        body.update(_kv(rest[5:]))
        _send("POST", f"/submolts/{rest[0]}/labels", body=body)
    elif cmd == "labels":
        _need(rest, 1, "labels SUBMOLT")
        _show(_request("GET", f"/submolts/{rest[0]}/labels"))
    elif cmd == "roles":
        _need(rest, 1, "roles SUBMOLT")
        _show(_request("GET", f"/submolts/{rest[0]}/roles"))
    elif cmd == "attach-label":
        _need(rest, 3, "attach-label DEF_ID TARGET_TYPE TARGET_ID [placement=metadata]")
        body = {"label_definition_id": rest[0], "target_type": rest[1], "target_id": rest[2]}
        body.update(_kv(rest[3:]))
        _send("POST", "/labels/attach", body=body)
    elif cmd == "detach-label":
        _need(rest, 1, "detach-label ATTACHMENT_ID")
        _send("DELETE", f"/labels/attach/{rest[0]}")

    # Verification and notification state.
    elif cmd == "verify":
        _need(rest, 2, "verify VERIFICATION_CODE ANSWER")
        _send("POST", "/verify", body={"verification_code": rest[0], "answer": rest[1]})
    elif cmd == "mark-read":
        _need(rest, 1, "mark-read POST_ID")
        _send("POST", f"/notifications/read-by-post/{rest[0]}")
    elif cmd == "mark-all-read":
        _send("POST", "/notifications/read-all")

    # Generic endpoints and registration.
    elif cmd == "get":
        _need(rest, 1, "get PATH [k=v ...]")
        _show(_request("GET", rest[0], query=_kv(rest[1:])))
    elif cmd == "post":
        _need(rest, 2, "post PATH JSON")
        _send("POST", rest[0], body=_json_arg(rest[1]))
    elif cmd == "patch":
        _need(rest, 2, "patch PATH JSON")
        _send("PATCH", rest[0], body=_json_arg(rest[1]))
    elif cmd == "delete":
        _need(rest, 1, "delete PATH [JSON]")
        body = _json_arg(rest[1]) if len(rest) > 1 else None
        _send("DELETE", rest[0], body=body)
    elif cmd == "register":
        _need(rest, 2, "register NAME DESCRIPTION")
        _send("POST", "/agents/register", body={"name": rest[0], "description": rest[1]}, auth=False)
    else:
        sys.exit(USAGE)


if __name__ == "__main__":
    main()
