"""Failure-isolated Iter transformations for the weak process runner.

The two-rule MeTTa kernel defines replacement and stutter.  This replaceable
adapter implements the corresponding ordered fold at a JSON process boundary
and exposes it to MeTTa.  A child process contains crashes and timeouts; it is
not a security sandbox and inherits the launcher's reachable environment.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import types
from typing import Any


DEFAULT_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class CapturedProcess:
    name: str
    display_path: str
    source: bytes
    digest: str


@dataclass(frozen=True)
class Snapshot:
    revision: str
    processes: tuple[CapturedProcess, ...]


@dataclass(frozen=True)
class Observation:
    name: str
    digest: str
    status: str
    detail: str = ""


@dataclass(frozen=True)
class RunResult:
    messages: Any
    tools: Any
    observations: tuple[Observation, ...]


def _digest(source: bytes) -> str:
    return hashlib.sha256(source).hexdigest()


def capture(directory: str | os.PathLike[str]) -> Snapshot:
    """Capture ordered entry-file bytes for one turn.

    Imports and files read by a transformation remain external observations;
    the revision identifies the captured entry files, not the whole world.
    """

    root = Path(directory)
    paths = sorted(
        path for path in root.glob("*.py") if not path.name.startswith("_")
    )
    processes = tuple(
        CapturedProcess(
            path.name, os.fspath(path.resolve()), source, _digest(source)
        )
        for path in paths
        for source in (path.read_bytes(),)
    )
    revision_input = b"".join(
        process.name.encode("utf-8") + b"\0"
        + process.digest.encode("ascii") + b"\0"
        for process in processes
    )
    return Snapshot(_digest(revision_input), processes)


def _timeout_seconds() -> float:
    raw = os.environ.get("METTACLAW_ITER_PROCESS_TIMEOUT_SECONDS")
    if raw is None:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        return max(0.01, float(raw))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def _python_executable() -> str:
    return os.environ.get("METTACLAW_PYTHON_EXECUTABLE", "python3")


def _write_result(path: Path, result: dict[str, Any]) -> None:
    try:
        encoded = json.dumps(result, ensure_ascii=False)
    except BaseException as error:
        encoded = json.dumps(
            {
                "ok": False,
                "error": (
                    "Result serialization failed: "
                    f"{type(error).__name__}: {error}"
                ),
            },
            ensure_ascii=False,
        )
    path.write_text(encoded, encoding="utf-8")


def _worker(payload_path: Path, result_path: Path) -> None:
    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        source = base64.b64decode(payload["source"], validate=True)
        display_path = payload["display_path"]
        module = types.ModuleType("_mettaclaw_iter_process")
        module.__file__ = display_path
        module.__package__ = None
        exec(compile(source, display_path, "exec"), module.__dict__)
        result = module.transform(payload["messages"], payload["tools"])
        if not isinstance(result, (list, tuple)) or len(result) != 2:
            raise TypeError("transform must return (messages, tools)")
        output = {"ok": True, "messages": result[0], "tools": result[1]}
    except BaseException as error:
        output = {"ok": False, "error": f"{type(error).__name__}: {error}"}
    _write_result(result_path, output)


def invoke(
    process: CapturedProcess,
    messages: Any,
    tools: Any,
) -> tuple[bool, Any, Any, str]:
    """Invoke one captured process without sharing mutable Python state."""

    with tempfile.TemporaryDirectory(prefix="mettaclaw-iter-process-") as directory:
        temporary = Path(directory)
        payload_path = temporary / "payload.json"
        result_path = temporary / "result.json"
        try:
            payload_path.write_text(
                json.dumps(
                    {
                        "source": base64.b64encode(process.source).decode("ascii"),
                        "display_path": process.display_path,
                        "messages": messages,
                        "tools": tools,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except BaseException as error:
            return False, messages, tools, (
                f"Payload serialization failed: {type(error).__name__}: {error}"
            )

        try:
            child = subprocess.Popen(
                [
                    _python_executable(),
                    str(Path(__file__).resolve()),
                    "--worker",
                    str(payload_path),
                    str(result_path),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        except BaseException as error:
            return False, messages, tools, (
                f"Process launch failed: {type(error).__name__}: {error}"
            )
        try:
            child.wait(timeout=_timeout_seconds())
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
            return False, messages, tools, "TIMEOUT"

        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except BaseException:
            return False, messages, tools, (
                f"Process exited with code {child.returncode} without a valid result"
            )
        if result.get("ok") is True:
            return True, result["messages"], result["tools"], ""
        return False, messages, tools, str(result.get("error", "invalid result"))


def run(snapshot: Snapshot, messages: Any, tools: Any) -> RunResult:
    """Fold one captured snapshot; a failed component is a local stutter."""

    observations = []
    current_messages, current_tools = messages, tools
    for process in snapshot.processes:
        ok, next_messages, next_tools, detail = invoke(
            process, current_messages, current_tools
        )
        if ok:
            current_messages, current_tools = next_messages, next_tools
            observations.append(
                Observation(process.name, process.digest, "success")
            )
        else:
            observations.append(
                Observation(process.name, process.digest, "failure", detail)
            )
    return RunResult(current_messages, current_tools, tuple(observations))


def run_directory(
    directory: str | os.PathLike[str], messages: Any, tools: Any
) -> tuple[Snapshot, RunResult]:
    snapshot = capture(directory)
    return snapshot, run(snapshot, messages, tools)


def run_json(directory: str, messages_json: str, tools_json: str) -> str:
    """Stable JSON bridge for a MeTTa policy adapter or a conformance probe."""

    snapshot, result = run_directory(
        directory, json.loads(messages_json), json.loads(tools_json)
    )
    return json.dumps(
        {
            "revision": snapshot.revision,
            "messages": result.messages,
            "tools": result.tools,
            "observations": [
                {
                    "name": item.name,
                    "digest": item.digest,
                    "status": item.status,
                    "detail": item.detail,
                }
                for item in result.observations
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
    )


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "--worker":
        raise SystemExit(
            "iter_process_adapter.py --worker PAYLOAD_PATH RESULT_PATH"
        )
    _worker(Path(sys.argv[2]), Path(sys.argv[3]))
