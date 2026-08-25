"""Bounded live projection of repositories and immutable Zahrada reports.

This is an atlas adapter, not another memory database. It rebuilds its view
from current Git identities and report files and never summarizes an earlier
generated context bundle.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time


ROOT = Path(__file__).resolve().parents[1]
_CACHE_SECONDS = 2.0
_lock = threading.RLock()
_cache: tuple[float, str] | None = None


def _run_git(path: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), *arguments],
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
        timeout=2, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("repository evidence probe failed")
    return result.stdout.strip()


def _default_registry() -> dict:
    return {
        "schema": 1,
        "projects": [{
            "id": "pettaclaw",
            "report_namespace": "pettaclaw",
            "checkouts": [{"path": str(ROOT), "role": "active"}],
        }],
    }


def _registry() -> dict:
    raw = os.environ.get("METTACLAW_PROJECT_REGISTRY_PATH", "").strip()
    value = (json.loads(Path(raw).read_text(encoding="utf-8"))
             if raw else _default_registry())
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise ValueError("project registry has an unsupported schema")
    if not isinstance(value.get("projects"), list):
        raise ValueError("project registry projects must be a list")
    return value


def _report_metadata(namespace: str, limit=4) -> list[str]:
    raw_root = os.environ.get("METTACLAW_REPORTS_ROOT", "").strip()
    if not raw_root:
        return []
    reports_root = Path(raw_root)
    directory = reports_root / namespace
    if not directory.is_dir():
        return []
    reports = sorted(directory.glob("*.md"), key=lambda item: item.name)[-limit:]
    rows = []
    for report in reports:
        raw = report.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        title = next((
            line.lstrip("# ").strip() for line in text.splitlines()
            if line.startswith("# ")
        ), report.stem)
        digest = hashlib.sha256(raw).hexdigest()[:16]
        rows.append("report=%s sha256=%s title=%s" % (
            report.name, digest, " ".join(title.split())[:180]
        ))
    return rows


def _render() -> str:
    lines = [
        "PROJECT EVIDENCE: Git state and immutable report identities are "
        "regenerated from their sources; report claims remain self-reports."
    ]
    for project in _registry()["projects"]:
        if not isinstance(project, dict) or not str(project.get("id", "")):
            raise ValueError("project registry entry has no id")
        project_id = str(project["id"])
        lines.append("PROJECT %s" % project_id)
        checkouts = project.get("checkouts", [])
        if not isinstance(checkouts, list):
            raise ValueError("project checkouts must be a list")
        for checkout in checkouts:
            if not isinstance(checkout, dict):
                raise ValueError("project checkout must be an object")
            path = Path(str(checkout.get("path", ""))).resolve()
            role = str(checkout.get("role", "checkout"))
            head = _run_git(path, "rev-parse", "HEAD")
            branch = _run_git(path, "branch", "--show-current") or "detached"
            dirty = bool(_run_git(
                path, "status", "--porcelain=v1", "--untracked-files=no"
            ))
            lines.append(
                "checkout role=%s branch=%s head=%s tracked-dirty=%s"
                % (role, branch, head, str(dirty).lower())
            )
        namespace = str(project.get("report_namespace", project_id))
        if not os.environ.get("METTACLAW_REPORTS_ROOT", "").strip():
            lines.append("reports-adapter=unconfigured")
        else:
            report_rows = _report_metadata(namespace)
            lines.extend(report_rows or ["reports=absent"])
    return "\n".join(lines)


def view() -> str:
    global _cache
    now = time.monotonic()
    with _lock:
        if _cache is not None and now - _cache[0] <= _CACHE_SECONDS:
            return _cache[1]
    rendered = _render()
    with _lock:
        _cache = (now, rendered)
    return rendered
