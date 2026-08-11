#!/usr/bin/env python3
"""Reject private runtime state or locally known secrets in public Git data."""

import argparse
import os
import pathlib
import re
import shlex
import subprocess
import sys


PRIVATE_EXACT = {
    ".env",
    "config/local.toml",
    "config/secrets.env",
    "telegram_offset.txt",
    "telegram_updates.jsonl",
}
PRIVATE_PREFIXES = (
    "archive/",
    "chat/",
    "chroma_db/",
    "episodes/",
    "memory/",
    "recovery/",
    "repos/",
    "to-claws/",
)
IDENTITY_KEYS = {
    "METTACLAW_TELEGRAM_ALLOWED_CHAT_IDS",
    "METTACLAW_TELEGRAM_LIGHT_ARM_IDS",
    "METTACLAW_TELEGRAM_OPERATOR_IDS",
    "METTACLAW_TELEGRAM_SENDER_NAMES",
}


def git(root, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=check,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def tracked_paths(root):
    raw = git(root, "ls-files", "-z").stdout
    return [part.decode("utf-8", "surrogateescape")
            for part in raw.split(b"\0") if part]


def private_path(path):
    return (
        path in PRIVATE_EXACT
        or path.endswith((".log", ".sqlite", ".sqlite3"))
        or path.startswith(PRIVATE_PREFIXES)
    )


def assignment_value(text):
    try:
        parts = shlex.split(text, comments=True, posix=True)
    except ValueError:
        return ""
    return parts[0] if parts else ""


def local_private_values(root):
    path = root / "config" / "secrets.env"
    if not path.is_file():
        return set()
    values = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, encoded = line.split("=", 1)
        key = key.strip()
        value = assignment_value(encoded)
        if not value:
            continue
        if (key in IDENTITY_KEYS
                or re.search(r"(?:KEY|TOKEN|SECRET|PASSWORD)$", key)):
            if len(value) >= 6:
                values.add(value.encode())
            if key in IDENTITY_KEYS:
                for identifier in re.findall(r"-?\d{6,}", value):
                    values.add(identifier.encode())
    return values


def indexed_blobs(root, paths):
    for path in paths:
        result = git(root, "show", ":" + path, check=False)
        if result.returncode == 0:
            yield path, result.stdout


def historical_blobs(root):
    objects = git(root, "rev-list", "--objects", "--all").stdout.splitlines()
    seen = set()
    for record in objects:
        oid, _, name = record.partition(b" ")
        if oid in seen:
            continue
        seen.add(oid)
        kind = git(root, "cat-file", "-t", oid.decode(), check=False)
        if kind.returncode != 0 or kind.stdout.strip() != b"blob":
            continue
        body = git(root, "cat-file", "blob", oid.decode()).stdout
        yield name.decode("utf-8", "surrogateescape") or oid.decode(), body


def audit(root, history=False):
    failures = []
    paths = tracked_paths(root)
    for path in paths:
        if private_path(path):
            failures.append("private path is tracked: " + path)

    private_values = local_private_values(root)
    blobs = historical_blobs(root) if history else indexed_blobs(root, paths)
    for path, body in blobs:
        if any(value in body for value in private_values):
            failures.append("local private value appears in Git data: " + path)

    if history and private_values:
        messages = git(root, "log", "--all", "--format=%B").stdout
        if any(value in messages for value in private_values):
            failures.append("local private value appears in commit metadata")

    for failure in sorted(set(failures)):
        print("public-tree audit failed: " + failure, file=sys.stderr)
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", action="store_true",
                        help="also scan every blob reachable from local refs")
    parser.add_argument("--repo", type=pathlib.Path,
                        default=pathlib.Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.repo.resolve()
    if not (root / ".git").exists():
        print("public-tree audit failed: not a Git worktree", file=sys.stderr)
        return 2
    return audit(root, args.history)


if __name__ == "__main__":
    raise SystemExit(main())
