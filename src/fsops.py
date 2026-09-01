"""Filesystem awareness for the agent loop, adapted from how coding
harnesses handle files: reads are line-numbered, edits are exact-string
replacements anchored to seen content with uniqueness enforced, and every
result string is itself the verification — success and failure are both
explicit, so no blind writes and no re-reading to check what landed."""

import os
import re

MAX_LINES = 200
MAX_MATCHES = 30
MAX_LINE_CHARS = 200
MAX_FILE_BYTES = 2_000_000
MAX_FILES_SCANNED = 2000
SKIP_DIRS = {".git", "__pycache__", "node_modules", "chroma_db", ".venv"}


def read_file(path):
    """Whole file as a string, or a reason. Never a silent empty result:
    'read failed: no such file: X (cwd Y)' is actionable; '' is a mystery."""
    path = str(path)
    try:
        with open(path, "rb") as f:
            data = f.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            return ("read failed: %s exceeds %d bytes — use read-lines for a "
                    "bounded window" % (path, MAX_FILE_BYTES))
        if not data:
            # An empty file and a failed read must never look alike.
            return "READ_OK_EMPTY_FILE: %s exists and holds zero bytes" % path
        return data.decode("utf-8", errors="replace")
    except FileNotFoundError:
        return "read failed: no such file: %s (cwd %s)" % (path, os.getcwd())
    except IsADirectoryError:
        return "read failed: %s is a directory — use (ls-tree %r 1)" % (path, path)
    except PermissionError:
        return "read failed: permission denied: %s" % path
    except OSError as exc:
        return "read failed (%s): %s" % (type(exc).__name__, exc)


def read_lines(path, start=1, count=60):
    """Numbered window of a file; the numbers are what edit anchors need."""
    path = str(path)
    try:
        with open(path, "rb") as fh:
            data = fh.read(MAX_FILE_BYTES + 1)
    except OSError as exc:
        return f"read-lines failed: {exc}"
    if len(data) > MAX_FILE_BYTES:
        return (f"read-lines failed: {path} exceeds {MAX_FILE_BYTES} bytes; "
                "use shell tools that stream a bounded range")
    if not data:
        # An empty file and a failed read must never look alike.
        return f"READ_OK_EMPTY_FILE: {path} exists and holds zero bytes"
    lines = data.decode("utf-8", errors="replace").splitlines()
    start = max(1, int(start))
    count = min(int(count), MAX_LINES)
    window = lines[start - 1:start - 1 + count]
    if not window:
        return f"{path}: {len(lines)} lines total; start {start} is past the end"
    body = "\n".join(f"{start + i:5d}\t{l[:MAX_LINE_CHARS]}"
                     for i, l in enumerate(window))
    return (f"{path}: {len(lines)} lines total, showing "
            f"{start}-{start + len(window) - 1}\n{body}")


def edit_file(path, old, new):
    """Exact-string replacement. The errors are the instructions."""
    path, old, new = str(path), str(old), str(new)
    if not old:
        return "edit-file failed: old-string is empty"
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        return f"edit-file failed: {exc}"
    n = text.count(old)
    if n == 0:
        return ("edit-file failed: old-string not found in %s — read-lines "
                "the region and copy the exact text (whitespace matters)" % path)
    if n > 1:
        return ("edit-file failed: old-string has %d matches in %s — include "
                "surrounding lines to make it unique" % (n, path))
    line = text[:text.index(old)].count("\n") + 1
    text = text.replace(old, new, 1)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except OSError as exc:
        return f"edit-file failed writing: {exc}"
    return (f"edited {path}: 1 replacement at line {line} "
            f"(file now {text.count(chr(10)) + 1} lines)")


def ls_tree(root, depth=2):
    """Compact indented tree: dirs first, sizes on files, bounded."""
    root = str(root)
    depth = min(max(int(depth), 1), 4)
    if not os.path.isdir(root):
        return f"ls-tree failed: not a directory: {root}"
    out, count = [root], 0

    def walk(d, level):
        nonlocal count
        try:
            entries = sorted(os.scandir(d), key=lambda e: (e.is_file(), e.name))
        except OSError as exc:
            out.append("  " * level + f"[{exc}]")
            return
        for e in entries:
            if e.name in SKIP_DIRS or e.name.startswith(".git"):
                continue
            if count >= 120:
                out.append("  " * level + "… (truncated at 120 entries)")
                return
            count += 1
            if e.is_dir(follow_symlinks=False):
                out.append("  " * level + e.name + "/")
                if level + 1 < depth:
                    walk(e.path, level + 1)
            else:
                try:
                    size = e.stat(follow_symlinks=False).st_size
                except OSError:
                    size = -1
                out.append("  " * level + f"{e.name}  ({size}b)")

    walk(root, 0)
    return "\n".join(out)


def grep_files(pattern, root):
    """path:line: text matches, bounded; regex or literal fallback."""
    root = str(root)
    try:
        rx = re.compile(str(pattern))
    except re.error:
        rx = re.compile(re.escape(str(pattern)))
    hits, scanned = [], 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS and not d.startswith(".git")]
        for name in filenames:
            if scanned >= MAX_FILES_SCANNED or len(hits) >= MAX_MATCHES:
                break
            fp = os.path.join(dirpath, name)
            try:
                if os.path.getsize(fp) > MAX_FILE_BYTES:
                    continue
                with open(fp, "rb") as fh:
                    head = fh.read(1024)
                    if b"\0" in head:
                        continue
                scanned += 1
                with open(fp, encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh, 1):
                        if rx.search(line):
                            hits.append(f"{fp}:{i}: {line.strip()[:MAX_LINE_CHARS]}")
                            if len(hits) >= MAX_MATCHES:
                                break
            except OSError:
                continue
        if scanned >= MAX_FILES_SCANNED or len(hits) >= MAX_MATCHES:
            break
    if not hits:
        return f"no matches for {pattern!r} under {root} ({scanned} files scanned)"
    note = " (result cap reached)" if len(hits) >= MAX_MATCHES else ""
    return f"{len(hits)} matches{note}:\n" + "\n".join(hits)
