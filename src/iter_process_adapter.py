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
DEFAULT_PROCESS_DIRECTORY = "memory/transformations"


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


def configured_directory() -> str:
    """The replaceable Iter process directory used by a live request."""

    return os.environ.get(
        "METTACLAW_ITER_PROCESS_DIR", DEFAULT_PROCESS_DIRECTORY
    )


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
        if not isinstance(result[0], list) or not isinstance(result[1], list):
            raise TypeError("transformed messages and tools must be lists")
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


def _enabled(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no")
    return bool(value)


def _request_tools(advertised: Any) -> list[dict[str, Any]]:
    """Represent the real prompt command surface as one broker capability.

    Individual MeTTa skills remain governed by the existing deterministic
    dispatcher.  Iter may rewrite what the model sees here, but this value is
    never used to resolve or authorize a command.
    """

    return [{
        "type": "function",
        "function": {
            "name": "command_batch",
            "description": str(advertised),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": True,
            },
        },
    }]


def prepare_request_json(
    system_message: Any,
    activity_message: Any,
    advertised: Any,
    run_iter: Any,
) -> str:
    """Capture and prepare one structured coding request.

    The child transformations receive only messages and advertised schemas.
    The executable/permitted authority remains the single command-batch
    dispatcher and is recorded, not passed to transformations.
    """

    messages = [
        {"role": "system", "content": str(system_message)},
        {"role": "user", "content": str(activity_message)},
    ]
    tools = _request_tools(advertised)
    directory = configured_directory()
    observations: tuple[Observation, ...] = ()
    revision = None
    if _enabled(run_iter):
        try:
            snapshot, result = run_directory(directory, messages, tools)
            revision = snapshot.revision
            messages, tools = result.messages, result.tools
            observations = result.observations
        except BaseException as error:
            observations = (
                Observation(
                    "request-adapter",
                    "",
                    "failure",
                    f"{type(error).__name__}: {error}",
                ),
            )
    return json.dumps(
        {
            "authority": {
                "executable": ["command-batch"],
                "permitted": ["command-batch"],
            },
            "messages": messages,
            "observations": [
                {
                    "name": item.name,
                    "digest": item.digest,
                    "status": item.status,
                    "detail": item.detail,
                }
                for item in observations
            ],
            "revision": revision,
            "tools": tools,
            "transformations_enabled": _enabled(run_iter),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _request_envelope(value: str) -> dict[str, Any]:
    envelope = json.loads(str(value))
    if not isinstance(envelope, dict):
        raise TypeError("prepared request must be a JSON object")
    return envelope


def _render_message(message: Any) -> str:
    if isinstance(message, dict) and "content" in message:
        role = str(message.get("role", "message")).upper()
        return f"{role}: {message['content']}"
    return "MESSAGE: " + json.dumps(message, ensure_ascii=False, sort_keys=True)


def render_request_json(value: str) -> str:
    """Render transformed order and advertisements for the current LLM API."""

    envelope = _request_envelope(value)
    messages = envelope.get("messages")
    tools = envelope.get("tools")
    if not isinstance(messages, list) or not isinstance(tools, list):
        raise TypeError("prepared messages and tools must be JSON lists")
    rendered_messages = "\n\n".join(_render_message(item) for item in messages)
    rendered_tools = json.dumps(
        tools, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    observations = render_observations_json(value)
    sections = [
        rendered_messages,
        "ADVERTISED_CAPABILITIES:\n" + rendered_tools,
    ]
    if observations:
        sections.append(observations)
    return "\n\n".join(sections)


def render_observations_json(value: str) -> str:
    """Bounded request-preparation evidence for context and turn receipts."""

    envelope = _request_envelope(value)
    observations = envelope.get("observations")
    if not isinstance(observations, list) or not observations:
        return ""
    items = []
    for observation in observations:
        if not isinstance(observation, dict):
            items.append("malformed-observation")
            continue
        item = "%s:%s" % (
            observation.get("name", "unknown"),
            observation.get("status", "unknown"),
        )
        detail = str(observation.get("detail") or "")
        if detail:
            item += ":" + detail[:500]
        items.append(item)
    revision = envelope.get("revision")
    return (
        "ITER_PROCESS_OBSERVATIONS revision=%s %s"
        % (revision or "none", "; ".join(items))
    )[:4000]


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "--worker":
        raise SystemExit(
            "iter_process_adapter.py --worker PAYLOAD_PATH RESULT_PATH"
        )
    _worker(Path(sys.argv[2]), Path(sys.argv[3]))
