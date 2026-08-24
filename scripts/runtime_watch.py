#!/usr/bin/env python3
"""Observe a deployed PettaClaw generation and manage its probation.

The watcher is outside the agent process. It combines process health with
channel, cognitive-boundary, and memory continuity observations. A candidate
that fails repeatedly during probation is atomically returned to the recorded
known-good Git generation; private runtime state is never switched or reset.
"""

import argparse
import datetime
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import runtime_health  # noqa: E402


def _run(command, cwd=None, check=False):
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                          timeout=30, check=check)


def _read_json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, TypeError, ValueError):
        return {}


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".deployment-", dir=path.parent,
                                     text=True)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _head(root):
    result = _run(["git", "rev-parse", "HEAD"], cwd=root, check=True)
    return result.stdout.strip()


def _service_active(service):
    return _run(["systemctl", "--user", "is-active", "--quiet", service]).returncode == 0


def _generation_has_lifecycle_authority(root, revision):
    """Refuse rollback across the operator-authority safety boundary."""
    required = {
        "src/lifecycle.py": ("def cognition_enabled", "def stop", "def start"),
        "src/loop.metta": ("lifecycle.cognition_enabled",),
        "channels/telegram.py": ('"/start", "/stop"',),
    }
    for relative, markers in required.items():
        result = _run(
            ["git", "show", "%s:%s" % (revision, relative)], cwd=root
        )
        if result.returncode != 0:
            return False
        if any(marker not in result.stdout for marker in markers):
            return False
    return True


def observe(args, deployment, now=None):
    now = time.time() if now is None else float(now)
    os.environ["METTACLAW_TELEGRAM_HEALTH_PATH"] = str(args.health)
    os.environ["METTACLAW_WORKING_SET_PATH"] = str(args.working_set)
    if getattr(args, "cognitive_health", None):
        os.environ["METTACLAW_COGNITIVE_HEALTH_PATH"] = str(
            args.cognitive_health)
    os.environ["METTACLAW_CHROMA_DIR"] = str(args.chroma)
    facts = runtime_health.status(now=now)
    problems = list(facts["problems"])
    active = _service_active(args.service)
    if not active:
        problems.append("service-inactive")
    try:
        head = _head(args.root)
    except (OSError, subprocess.SubprocessError):
        head = "unknown"
        problems.append("generation-unreadable")
    if deployment.get("status") == "probation" and head != deployment.get("candidate"):
        problems.append("candidate-generation-mismatch")
    canonical_bytes = (args.canonical_memory.stat().st_size
                       if args.canonical_memory.exists() else 0)
    if canonical_bytes < int(deployment.get("baseline_canonical_bytes", 0)):
        problems.append("canonical-memory-regressed")
    if facts["memories"] < int(deployment.get("baseline_memories", 0)):
        problems.append("memory-count-regressed")
    return {
        "observed_at": now, "active": active, "head": head,
        "canonical_memory_bytes": canonical_bytes,
        "runtime": facts, "problems": sorted(set(problems)),
    }


def _rollback(args, deployment, observation):
    root = args.root
    if observation["head"] != deployment.get("candidate"):
        return False, "rollback-refused-generation-mismatch"
    if not _generation_has_lifecycle_authority(
            root, deployment.get("previous", "")):
        return False, "rollback-refused-lifecycle-regression"
    if (_run(["git", "diff", "--quiet"], cwd=root).returncode != 0
            or _run(["git", "diff", "--cached", "--quiet"], cwd=root).returncode != 0):
        return False, "rollback-refused-dirty-tree"
    _run(["systemctl", "--user", "stop", args.service], check=True)
    try:
        _run(["git", "switch", "--detach", deployment["previous"]],
             cwd=root, check=True)
    except Exception:
        _run(["systemctl", "--user", "start", args.service])
        raise
    _run(["systemctl", "--user", "start", args.service], check=True)
    return True, "rolled-back-to-known-good"


def manage(args, now=None):
    now = time.time() if now is None else float(now)
    deployment = _read_json(args.deployment)
    if not deployment:
        raise RuntimeError("deployment state is missing or invalid")
    observation = observe(args, deployment, now=now)
    problems = observation["problems"]
    action = "none"
    if problems:
        deployment["consecutive_failures"] = int(
            deployment.get("consecutive_failures", 0)) + 1
        if not observation["active"]:
            _run(["systemctl", "--user", "restart", args.service])
            action = "service-restarted"
        if (deployment.get("status") == "probation"
                and now < float(deployment.get("probation_until", 0))
                and deployment["consecutive_failures"] >= args.failures):
            success, action = _rollback(args, deployment, observation)
            if success:
                deployment["status"] = "rolled_back"
                deployment["rolled_back_at"] = now
                deployment["rollback_problems"] = problems
                deployment["consecutive_failures"] = 0
        elif deployment["consecutive_failures"] >= args.failures:
            _run(["systemctl", "--user", "restart", args.service])
            action = "service-restarted-after-repeated-failure"
            deployment["consecutive_failures"] = 0
    else:
        deployment["consecutive_failures"] = 0
        if (deployment.get("status") == "probation"
                and now >= float(deployment.get("probation_until", 0))):
            deployment["status"] = "accepted"
            deployment["accepted_at"] = now
            deployment["last_good"] = observation["head"]
            action = "candidate-accepted"
    deployment["last_observation"] = observation
    deployment["last_action"] = action
    _write_json(args.deployment, deployment)
    line = {
        "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "state": "ok" if not problems else "problem",
        "problems": problems, "action": action,
        "head": observation["head"][:12],
    }
    args.log.parent.mkdir(parents=True, exist_ok=True)
    with args.log.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(line, sort_keys=True) + "\n")
    print(json.dumps(line, sort_keys=True))
    return 0 if not problems else 1


def parser():
    result = argparse.ArgumentParser()
    result.add_argument("--root", required=True, type=pathlib.Path)
    result.add_argument("--service", required=True)
    result.add_argument("--health", required=True, type=pathlib.Path)
    result.add_argument("--working-set", required=True, type=pathlib.Path)
    result.add_argument("--cognitive-health", type=pathlib.Path)
    result.add_argument("--canonical-memory", required=True, type=pathlib.Path)
    result.add_argument("--chroma", required=True, type=pathlib.Path)
    result.add_argument("--deployment", required=True, type=pathlib.Path)
    result.add_argument("--log", required=True, type=pathlib.Path)
    result.add_argument("--failures", type=int, default=3)
    return result


if __name__ == "__main__":
    raise SystemExit(manage(parser().parse_args()))
