"""Proof-boundary primitives for protected self-modification.

The agent process may prepare immutable proposals.  Only a separately launched
supervisor with a writable view of the protected root may promote one.  The
security boundary is the supervisor's filesystem authority, not this module.
"""

from __future__ import annotations

import dataclasses
import datetime as _datetime
import errno
import hashlib
import json
import os
import pathlib
import re
import stat
import subprocess
import tempfile
from typing import Callable, Optional


SCHEMA_VERSION = 1
MAX_CANDIDATE_BYTES = 2_000_000
MAX_PROVENANCE_CHARS = 2_000
PROPOSAL_ID_RE = re.compile(r"^[0-9a-f]{64}$")


class SelfModError(RuntimeError):
    """A fail-closed proposal or promotion error."""


@dataclasses.dataclass(frozen=True)
class Settings:
    root: pathlib.Path
    store: pathlib.Path
    petta_root: pathlib.Path
    parser_helper: pathlib.Path
    python_env: Optional[pathlib.Path] = None
    swipl: str = "swipl"
    timeout_seconds: int = 8

    @classmethod
    def from_env(cls, root=None, store=None):
        module_root = pathlib.Path(__file__).resolve().parents[1]
        requested_root = pathlib.Path(
            root or os.environ.get("METTACLAW_PROTECTED_ROOT", module_root)
        ).absolute()
        resolved_root = requested_root.resolve(strict=True)
        if requested_root != resolved_root:
            raise SelfModError("protected root itself must not be a symlink")
        if not resolved_root.is_dir():
            raise SelfModError("protected root is not a directory")

        state_home = pathlib.Path(
            os.environ.get(
                "XDG_STATE_HOME",
                pathlib.Path.home() / ".local" / "state",
            )
        )
        instance = os.environ.get("METTACLAW_INSTANCE", resolved_root.name)
        proposal_store = pathlib.Path(
            store
            or os.environ.get(
                "METTACLAW_SELFMOD_PROPOSAL_STORE",
                state_home / instance / "selfmod-proposals",
            )
        ).absolute()
        petta_root = pathlib.Path(
            os.environ.get("PETTA_ROOT", pathlib.Path.home() / "repos" / "PeTTa")
        ).resolve(strict=True)
        parser_helper = pathlib.Path(
            os.environ.get(
                "METTACLAW_METTA_PARSE_HELPER",
                module_root / "scripts" / "metta_parse_only.pl",
            )
        ).resolve(strict=True)
        requested_python_env = pathlib.Path(
            os.environ.get(
                "PETTA_PY_ENV",
                os.environ.get(
                    "METTACLAW_PYTHON_ENV",
                    pathlib.Path.home() / "miniforge3" / "envs" / "petta",
                ),
            )
        )
        python_env = (
            requested_python_env.resolve(strict=True)
            if requested_python_env.is_dir()
            else None
        )
        return cls(
            root=resolved_root,
            store=proposal_store,
            petta_root=petta_root,
            parser_helper=parser_helper,
            python_env=python_env,
            swipl=os.environ.get("METTACLAW_SWIPL", "swipl"),
            timeout_seconds=max(
                1, int(os.environ.get("METTACLAW_SELFMOD_TIMEOUT", "8"))
            ),
        )


@dataclasses.dataclass(frozen=True)
class PreparedChange:
    operation: str
    target: str
    candidate: bytes
    candidate_sha256: str
    base_sha256: Optional[str]
    base_exists: bool
    provenance: dict

    def policy_summary(self):
        return {
            "schema": SCHEMA_VERSION,
            "operation": self.operation,
            "target": self.target,
            "candidate_sha256": self.candidate_sha256,
            "candidate_size": len(self.candidate),
            "base_sha256": self.base_sha256,
            "base_exists": self.base_exists,
            "provenance": self.provenance,
        }


@dataclasses.dataclass(frozen=True)
class VerifiedProposal:
    proposal_id: str
    manifest: dict
    candidate: bytes
    target_parts: tuple[str, ...]
    current_mode: int


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _write_all(fd, data):
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise SelfModError("short write while persisting proposal")
        view = view[written:]


def _utc_now():
    return _datetime.datetime.now(_datetime.timezone.utc).isoformat()


def _bounded_text(value, limit=MAX_PROVENANCE_CHARS):
    text = str(value or "")
    if len(text) > limit:
        raise SelfModError("provenance field is too large")
    return text


def _provenance(operation, reason="", actor=None):
    return {
        "actor": _bounded_text(
            actor or os.environ.get("METTACLAW_SELFMOD_ACTOR", "agent")
        ),
        "source": "pettaclaw-structured-file-tool",
        "operation": operation,
        "reason": _bounded_text(reason),
        "created_at": _utc_now(),
    }


def _target_parts(settings, target):
    raw = os.fspath(target)
    if not raw or "\x00" in raw:
        raise SelfModError("target path is empty or contains NUL")
    raw_path = pathlib.Path(raw)
    if ".." in raw_path.parts:
        raise SelfModError("target path may not contain '..'")
    if raw_path.is_absolute():
        try:
            relative = raw_path.relative_to(settings.root)
        except ValueError as exc:
            raise SelfModError("target is outside the protected root") from exc
    else:
        relative = raw_path
    parts = tuple(part for part in relative.parts if part not in ("", "."))
    if not parts or any(part in ("..", os.sep) for part in parts):
        raise SelfModError("target must name a file beneath the protected root")
    return parts


def _open_parent(settings, parts):
    flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    root_fd = os.open(settings.root, flags)
    current_fd = root_fd
    try:
        for component in parts[:-1]:
            child_flags = flags
            if hasattr(os, "O_NOFOLLOW"):
                child_flags |= os.O_NOFOLLOW
            child_fd = os.open(component, child_flags, dir_fd=current_fd)
            if current_fd != root_fd:
                os.close(current_fd)
            current_fd = child_fd
        if current_fd == root_fd:
            root_fd = -1
        return current_fd
    except OSError as exc:
        if current_fd != root_fd:
            os.close(current_fd)
        raise SelfModError("target parent is missing, non-directory, or a symlink") from exc
    finally:
        if root_fd >= 0:
            os.close(root_fd)


def _read_current(settings, parts):
    parent_fd = _open_parent(settings, parts)
    try:
        flags = os.O_RDONLY
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(parts[-1], flags, dir_fd=parent_fd)
        except FileNotFoundError:
            return None, 0o644
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                raise SelfModError("target is a symlink or non-file") from exc
            raise
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise SelfModError("target is not a regular file")
            chunks = []
            total = 0
            while True:
                chunk = os.read(fd, 131072)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_CANDIDATE_BYTES:
                    raise SelfModError("target exceeds the self-modification size limit")
                chunks.append(chunk)
            return b"".join(chunks), stat.S_IMODE(info.st_mode)
        finally:
            os.close(fd)
    finally:
        os.close(parent_fd)


def _candidate_bytes(content):
    if not isinstance(content, str):
        content = str(content)
    data = content.encode("utf-8", errors="strict")
    if len(data) > MAX_CANDIDATE_BYTES:
        raise SelfModError("candidate exceeds the self-modification size limit")
    return data


def prepare_write(target, content, reason="", actor=None, settings=None):
    settings = settings or Settings.from_env()
    parts = _target_parts(settings, target)
    current, _ = _read_current(settings, parts)
    candidate = _candidate_bytes(content)
    return PreparedChange(
        operation="write",
        target="/".join(parts),
        candidate=candidate,
        candidate_sha256=_sha256(candidate),
        base_sha256=None if current is None else _sha256(current),
        base_exists=current is not None,
        provenance=_provenance("write", reason, actor),
    )


def prepare_edit(target, old, new, reason="", actor=None, settings=None):
    settings = settings or Settings.from_env()
    parts = _target_parts(settings, target)
    current, _ = _read_current(settings, parts)
    if current is None:
        raise SelfModError("edit target does not exist")
    try:
        text = current.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SelfModError("edit target is not UTF-8") from exc
    old = str(old)
    new = str(new)
    if not old:
        raise SelfModError("edit old-string is empty")
    occurrences = text.count(old)
    if occurrences != 1:
        raise SelfModError(
            "edit old-string must occur exactly once; found %d" % occurrences
        )
    candidate = _candidate_bytes(text.replace(old, new, 1))
    return PreparedChange(
        operation="edit",
        target="/".join(parts),
        candidate=candidate,
        candidate_sha256=_sha256(candidate),
        base_sha256=_sha256(current),
        base_exists=True,
        provenance=_provenance("edit", reason, actor),
    )


def prepare_append(target, content, reason="", actor=None, settings=None):
    settings = settings or Settings.from_env()
    parts = _target_parts(settings, target)
    current, _ = _read_current(settings, parts)
    if current is None:
        raise SelfModError("append target does not exist")
    suffix = _candidate_bytes(str(content) + "\n")
    candidate = current + suffix
    if len(candidate) > MAX_CANDIDATE_BYTES:
        raise SelfModError("candidate exceeds the self-modification size limit")
    return PreparedChange(
        operation="append",
        target="/".join(parts),
        candidate=candidate,
        candidate_sha256=_sha256(candidate),
        base_sha256=_sha256(current),
        base_exists=True,
        provenance=_provenance("append", reason, actor),
    )


def _sanitized_detail(text, settings):
    detail = str(text or "").strip()
    for private_path in (settings.root, settings.store, settings.petta_root):
        detail = detail.replace(str(private_path), "<root>")
    return detail[-1000:]


def check_metta_syntax(candidate_path, settings):
    command = [
        settings.swipl,
        "--stack_limit=1g",
        "-q",
        "-s",
        str(settings.parser_helper),
        "--",
        str(settings.petta_root),
        str(candidate_path),
    ]
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=settings.timeout_seconds,
            env={"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SelfModError("MeTTa parser infrastructure failed: %s" % type(exc).__name__)
    if result.returncode != 0:
        raise SelfModError(
            "MeTTa parser rejected candidate: "
            + _sanitized_detail(result.stderr, settings)
        )
    return {"kind": "petta-top-forms+sread", "status": "pass"}


def check_syntax(prepared, candidate_path, settings):
    suffix = pathlib.PurePosixPath(prepared.target).suffix.lower()
    if suffix == ".metta":
        return check_metta_syntax(candidate_path, settings)
    return {"kind": "not-applicable", "status": "pass"}


def _is_metta_target(target):
    return pathlib.PurePosixPath(target).suffix.lower() == ".metta"


def check_semantics(candidate_path, settings):
    """Evaluate a candidate directly with the agent process's authority.

    This is deliberately not a filesystem, process, or network sandbox.
    Semantic evaluation is optional and must not be represented as isolation.
    """
    command = [
        settings.swipl,
        "--stack_limit=1g",
        "-q",
        "-s",
        str(settings.petta_root / "src" / "main.pl"),
        "--",
        str(candidate_path),
        "default",
    ]
    environment = os.environ.copy()
    if settings.python_env is not None:
        python_bin = str(settings.python_env / "bin")
        python_lib = str(settings.python_env / "lib")
        environment["PATH"] = python_bin + os.pathsep + environment.get(
            "PATH", ""
        )
        environment["PYTHONHOME"] = str(settings.python_env)
        environment["PYTHONNOUSERSITE"] = "1"
        environment["LD_LIBRARY_PATH"] = python_lib + (
            os.pathsep + environment["LD_LIBRARY_PATH"]
            if environment.get("LD_LIBRARY_PATH") else ""
        )
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=settings.timeout_seconds,
            env=environment,
            cwd=str(candidate_path.parent),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SelfModError("semantic check failed: %s" % type(exc).__name__)
    if result.returncode != 0 or "ERROR:" in (result.stderr or ""):
        raise SelfModError(
            "semantic check rejected candidate: "
            + _sanitized_detail(result.stderr, settings)
        )
    return {"kind": "petta-direct-eval", "status": "pass"}


def _atomic_json(path, value):
    temporary = path.with_name(path.name + ".tmp")
    payload = json.dumps(value, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        _write_all(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, path)


def _proposal_identity(manifest):
    return {
        key: manifest[key]
        for key in (
            "schema",
            "operation",
            "target",
            "candidate_sha256",
            "candidate_size",
            "base_sha256",
            "base_exists",
            "provenance",
            "root_identity",
            "proposal_nonce",
        )
    }


def _compute_proposal_id(manifest):
    canonical = json.dumps(
        _proposal_identity(manifest), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return _sha256(canonical)


def _ensure_store(settings):
    if settings.store.is_symlink():
        raise SelfModError("proposal store may not be a symlink")
    settings.store.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not settings.store.is_dir() or settings.store.is_symlink():
        raise SelfModError("proposal store is not a real directory")
    resolved_store = settings.store.resolve(strict=True)
    if resolved_store != settings.store:
        raise SelfModError("proposal store path may not contain symlinks")
    try:
        resolved_store.relative_to(settings.root)
    except ValueError:
        pass
    else:
        raise SelfModError("proposal store must be outside the protected root")
    os.chmod(settings.store, 0o700)


def _save_proposal(prepared, syntax_receipt, semantic_receipt, settings):
    _ensure_store(settings)
    root_stat = settings.root.stat()
    manifest = prepared.policy_summary()
    manifest.update(
        {
            "root_identity": {
                "device": root_stat.st_dev,
                "inode": root_stat.st_ino,
            },
            "proposal_nonce": os.urandom(32).hex(),
            "syntax": syntax_receipt,
            "semantic": semantic_receipt,
            "state": "ready",
        }
    )
    proposal_id = _compute_proposal_id(manifest)
    manifest["proposal_id"] = proposal_id
    final_dir = settings.store / proposal_id
    temporary_dir = pathlib.Path(
        tempfile.mkdtemp(prefix=".proposal-", dir=settings.store)
    )
    try:
        os.chmod(temporary_dir, 0o700)
        candidate_path = temporary_dir / "candidate"
        fd = os.open(candidate_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            _write_all(fd, prepared.candidate)
            os.fsync(fd)
        finally:
            os.close(fd)
        _atomic_json(temporary_dir / "manifest.json", manifest)
        os.rename(temporary_dir, final_dir)
        return manifest
    except Exception:
        for child in temporary_dir.iterdir() if temporary_dir.exists() else ():
            child.unlink(missing_ok=True)
        temporary_dir.rmdir() if temporary_dir.exists() else None
        raise


def propose(
    prepared,
    settings=None,
    policy: Optional[Callable[[dict], str]] = None,
    semantic=False,
):
    settings = settings or Settings.from_env()
    with tempfile.TemporaryDirectory(prefix="pettaclaw-selfmod-") as tmp:
        candidate_path = pathlib.Path(tmp) / "candidate"
        candidate_path.write_bytes(prepared.candidate)
        syntax_receipt = check_syntax(prepared, candidate_path, settings)
        if semantic and _is_metta_target(prepared.target):
            semantic_receipt = check_semantics(candidate_path, settings)
        elif semantic:
            semantic_receipt = {
                "kind": "petta-direct-eval",
                "status": "not-applicable",
            }
        else:
            semantic_receipt = {
                "kind": "petta-direct-eval",
                "status": "not-requested",
            }
    if policy is not None:
        verdict = str(policy(prepared.policy_summary())).strip().upper()
        if verdict != "PASS":
            raise SelfModError("governance gate rejected proposal")
    return _save_proposal(prepared, syntax_receipt, semantic_receipt, settings)


def _load_candidate(proposal_id, settings):
    if not PROPOSAL_ID_RE.fullmatch(str(proposal_id)):
        raise SelfModError("invalid proposal id")
    proposal_dir = settings.store / proposal_id
    if proposal_dir.is_symlink() or not proposal_dir.is_dir():
        raise SelfModError("proposal does not exist or is not a real directory")
    manifest_path = proposal_dir / "manifest.json"
    candidate_path = proposal_dir / "candidate"
    if manifest_path.is_symlink() or candidate_path.is_symlink():
        raise SelfModError("proposal files may not be symlinks")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        candidate = candidate_path.read_bytes()
    except (OSError, ValueError) as exc:
        raise SelfModError("proposal is unreadable") from exc
    if manifest.get("schema") != SCHEMA_VERSION:
        raise SelfModError("unsupported proposal schema")
    if manifest.get("proposal_id") != proposal_id or manifest.get("state") != "ready":
        raise SelfModError("proposal identity or state is invalid")
    try:
        expected_proposal_id = _compute_proposal_id(manifest)
    except (KeyError, TypeError, ValueError) as exc:
        raise SelfModError("proposal identity fields are incomplete") from exc
    if expected_proposal_id != proposal_id:
        raise SelfModError("proposal manifest digest mismatch")
    if manifest.get("operation") not in {"write", "edit", "append"}:
        raise SelfModError("proposal operation is invalid")
    if len(candidate) > MAX_CANDIDATE_BYTES:
        raise SelfModError("proposal candidate is too large")
    if _sha256(candidate) != manifest.get("candidate_sha256"):
        raise SelfModError("proposal candidate digest mismatch")
    if len(candidate) != manifest.get("candidate_size"):
        raise SelfModError("proposal candidate size mismatch")
    return manifest, candidate, candidate_path


def verify_proposal(proposal_id, settings=None, semantic=False):
    settings = settings or Settings.from_env()
    manifest, candidate, candidate_path = _load_candidate(proposal_id, settings)
    root_stat = settings.root.stat()
    if manifest.get("root_identity") != {
        "device": root_stat.st_dev,
        "inode": root_stat.st_ino,
    }:
        raise SelfModError("proposal was prepared for a different protected root")
    parts = _target_parts(settings, manifest.get("target", ""))
    current, mode = _read_current(settings, parts)
    current_digest = None if current is None else _sha256(current)
    if current_digest != manifest.get("base_sha256"):
        raise SelfModError("proposal is stale: protected target changed")
    if (current is not None) != bool(manifest.get("base_exists")):
        raise SelfModError("proposal base-existence claim is invalid")
    prepared = PreparedChange(
        operation=manifest.get("operation", ""),
        target=manifest["target"],
        candidate=candidate,
        candidate_sha256=manifest["candidate_sha256"],
        base_sha256=manifest.get("base_sha256"),
        base_exists=bool(manifest.get("base_exists")),
        provenance=manifest.get("provenance", {}),
    )
    check_syntax(prepared, candidate_path, settings)
    if semantic and _is_metta_target(prepared.target):
        check_semantics(candidate_path, settings)
    return VerifiedProposal(
        proposal_id=proposal_id,
        manifest=manifest,
        candidate=candidate,
        target_parts=parts,
        current_mode=mode,
    )


def atomic_promote(verified, settings=None):
    settings = settings or Settings.from_env()
    parent_fd = _open_parent(settings, verified.target_parts)
    leaf = verified.target_parts[-1]
    temporary = ".selfmod-%s.tmp" % verified.proposal_id[:16]
    fd = None
    try:
        current, _ = _read_current(settings, verified.target_parts)
        current_digest = None if current is None else _sha256(current)
        if current_digest != verified.manifest.get("base_sha256"):
            raise SelfModError("proposal became stale before promotion")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(temporary, flags, verified.current_mode or 0o644, dir_fd=parent_fd)
        _write_all(fd, verified.candidate)
        os.fsync(fd)
        os.fchmod(fd, verified.current_mode or 0o644)
        os.close(fd)
        fd = None
        current, _ = _read_current(settings, verified.target_parts)
        current_digest = None if current is None else _sha256(current)
        if current_digest != verified.manifest.get("base_sha256"):
            raise SelfModError("proposal became stale during promotion")
        os.replace(temporary, leaf, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.fsync(parent_fd)
    except Exception:
        if fd is not None:
            os.close(fd)
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        raise
    finally:
        os.close(parent_fd)
    receipt = {
        "schema": SCHEMA_VERSION,
        "proposal_id": verified.proposal_id,
        "target": verified.manifest["target"],
        "candidate_sha256": verified.manifest["candidate_sha256"],
        "promoted_at": _utc_now(),
        "state": "promoted",
    }
    _atomic_json(settings.store / verified.proposal_id / "promotion.json", receipt)
    return receipt
