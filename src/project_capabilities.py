"""Compact capability facts witnessed from configured project artifacts."""

import hashlib
import os
import re
import subprocess
import threading

import engine_modes


_INVENTORY_ROW = re.compile(
    r"^\s+(\S+)\s+(implemented|planned)\s+(.+?)\s*$")
_lock = threading.RLock()
_cache = {}


def parse_cetta_inventory(text):
    """Parse only explicit inventory rows; surrounding help text is inert."""
    rows = []
    for line in str(text).splitlines():
        match = _INVENTORY_ROW.match(line)
        if match:
            rows.append(match.groups())
    return rows


def _run(argv):
    result = subprocess.run(
        list(argv), stdin=subprocess.DEVNULL, capture_output=True,
        text=True, timeout=3, check=False)
    if result.returncode != 0:
        raise RuntimeError("capability probe failed")
    return result.stdout.strip()


def _cetta_view(command):
    version = _run(command + ("--version",))
    raw_inventory = _run(command + ("--list-languages",))
    rows = parse_cetta_inventory(raw_inventory)
    if not version or not rows:
        raise RuntimeError("capability probe returned no inventory")
    digest = hashlib.sha256(
        (version + "\n" + raw_inventory).encode("utf-8", "replace")
    ).hexdigest()[:16]
    lines = [
        "artifact=cetta revision=%s inventory-sha256=%s" % (version, digest),
    ]
    for name, status, description in rows:
        lines.append("%s %s — %s" % (status, name, description))
    return "\n".join(lines)


def view():
    """Return a revision-bound CeTTa inventory, cached by artifact identity.

    Absence returns no source. Probe failures raise so the generic context
    projector can distinguish unavailable from genuinely absent.
    """
    command = tuple(engine_modes.engine_command("cetta"))
    if not command or not os.path.isfile(command[0]):
        return None
    stat = os.stat(command[0])
    key = (command, stat.st_mtime_ns, stat.st_size)
    with _lock:
        cached = _cache.get(key)
    if cached is not None:
        return cached
    rendered = _cetta_view(command)
    with _lock:
        _cache.clear()
        _cache[key] = rendered
    return rendered
