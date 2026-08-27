"""Direct, atomic authoring for Iter's mutable transformation directory.

This is the reprogramming seam from upstream Iter, not a protected-source
promotion mechanism.  A write changes the directory observed by the *next*
request capture.  An in-flight request retains its already captured bytes.
Syntax errors are reported but deliberately do not block installation: the
ordinary Iter reducer will witness the failure and stutter locally.

The name check keeps this operation scoped to one transformation entry.  It is
not a sandbox or a restriction on the separately advertised shell authority.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any

import iter_process_adapter


SCHEMA_VERSION = 1


class AuthoringError(ValueError):
    """An invalid transformation entry or unavailable filesystem operation."""


def _sha256(source: bytes) -> str:
    return hashlib.sha256(source).hexdigest()


def _directory() -> Path:
    return Path(iter_process_adapter.configured_directory())


def _active_name(value: Any) -> str:
    name = str(value)
    if (
        not name
        or name in {".", ".."}
        or name.startswith("_")
        or not name.endswith(".py")
        or Path(name).name != name
        or "\x00" in name
    ):
        raise AuthoringError(
            "name must be one active .py entry without a path or leading _"
        )
    return name


def _snapshot_revision(directory: Path) -> str:
    return iter_process_adapter.capture(directory).revision


def _read_regular(path: Path) -> bytes | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise AuthoringError("transformation entry is not a regular file")
    return path.read_bytes()


def _sync_directory(directory: Path) -> tuple[str, str]:
    """Best-effort durability witness after an already committed rename."""

    try:
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        descriptor = os.open(directory, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return "pass", ""
    except OSError as error:
        # The rename has already happened.  Preserve that fact in the receipt
        # instead of reporting a generic failure that could invite replay.
        return "unconfirmed", "%s: %s" % (type(error).__name__, error)


def _atomic_write(path: Path, source: bytes, mode: int) -> tuple[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".iter-author-", suffix=".tmp", dir=path.parent
    )
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(source)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        return _sync_directory(path.parent)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _syntax(source: str, filename: str) -> tuple[str, str]:
    try:
        compile(source, filename, "exec")
        return "pass", ""
    except (SyntaxError, ValueError) as error:
        detail = str(error)
        if isinstance(error, SyntaxError):
            detail = "%s at line %s" % (error.msg, error.lineno or "unknown")
        return "fail", detail


def _encoded(value: dict[str, Any]) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _failure(operation: str, name: Any, error: BaseException) -> str:
    return _encoded({
        "schema": SCHEMA_VERSION,
        "operation": operation,
        "name": str(name),
        "state": "error",
        "error": "%s: %s" % (type(error).__name__, error),
    })


def write_transformation(name: Any, source: Any) -> str:
    """Install or replace one active transformation for the next capture."""

    try:
        active = _active_name(name)
        text = str(source)
        raw = text.encode("utf-8")
        directory = _directory()
        target = directory / active
        before_revision = _snapshot_revision(directory)
        prior = _read_regular(target)
        mode = (target.stat().st_mode & 0o777) if prior is not None else 0o660
        syntax, syntax_error = _syntax(text, active)
        directory_sync, directory_sync_error = _atomic_write(target, raw, mode)
        observed = _read_regular(target)
        if observed != raw:
            raise AuthoringError("installed bytes changed before receipt")
        after_revision = _snapshot_revision(directory)
        return _encoded({
            "schema": SCHEMA_VERSION,
            "operation": "write",
            "name": active,
            "state": "installed",
            "active": True,
            "activation": "next-request-capture",
            "sha256": _sha256(raw),
            "prior_sha256": None if prior is None else _sha256(prior),
            "before_revision": before_revision,
            "activation_revision": after_revision,
            "syntax": syntax,
            "syntax_error": syntax_error,
            "directory_sync": directory_sync,
            "directory_sync_error": directory_sync_error,
        })
    except (OSError, UnicodeError, AuthoringError) as error:
        return _failure("write", name, error)


def _move(name: Any, enable: bool) -> str:
    operation = "enable" if enable else "disable"
    try:
        active = _active_name(name)
        directory = _directory()
        source = directory / (("_" + active) if enable else active)
        target = directory / (active if enable else ("_" + active))
        before_revision = _snapshot_revision(directory)
        raw = _read_regular(source)
        if raw is None:
            raise AuthoringError("source transformation does not exist")
        if target.exists() or target.is_symlink():
            raise AuthoringError("destination transformation already exists")
        os.replace(source, target)
        directory_sync, directory_sync_error = _sync_directory(directory)
        after_revision = _snapshot_revision(directory)
        return _encoded({
            "schema": SCHEMA_VERSION,
            "operation": operation,
            "name": active,
            "state": "enabled" if enable else "disabled",
            "active": enable,
            "activation": "next-request-capture",
            "sha256": _sha256(raw),
            "before_revision": before_revision,
            "activation_revision": after_revision,
            "directory_sync": directory_sync,
            "directory_sync_error": directory_sync_error,
        })
    except (OSError, AuthoringError) as error:
        return _failure(operation, name, error)


def disable_transformation(name: Any) -> str:
    """Atomically hide an active entry using Iter's leading-underscore rule."""

    return _move(name, enable=False)


def enable_transformation(name: Any) -> str:
    """Atomically reactivate a previously disabled entry."""

    return _move(name, enable=True)


def list_transformations() -> str:
    """Return active and disabled entry identities without executing them."""

    try:
        directory = _directory()
        snapshot = iter_process_adapter.capture(directory)
        disabled = []
        if directory.is_dir():
            for path in sorted(directory.glob("_*.py")):
                raw = _read_regular(path)
                if raw is not None:
                    disabled.append({"name": path.name, "sha256": _sha256(raw)})
        return _encoded({
            "schema": SCHEMA_VERSION,
            "state": "observed",
            "revision": snapshot.revision,
            "active": [
                {"name": item.name, "sha256": item.digest}
                for item in snapshot.processes
            ],
            "disabled": disabled,
        })
    except (OSError, AuthoringError) as error:
        return _failure("list", "", error)
