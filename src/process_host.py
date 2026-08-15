"""Failure-isolated dynamic processes for the weak MeTTa process core."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


DEFAULT_TIMEOUT_SECONDS = 5.0


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


def _worker(process_path: Path, payload_path: Path, result_path: Path) -> None:
    try:
        periphery = json.loads(payload_path.read_text(encoding="utf-8"))
        spec = importlib.util.spec_from_file_location(
            f"_three_policy_process_{process_path.stem}", process_path
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load process module {process_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        next_periphery = module.transform(periphery)
        result = {"ok": True, "next": next_periphery}
    except BaseException as error:
        result = {"ok": False, "error": f"{type(error).__name__}: {error}"}
    _write_result(result_path, result)


def _timeout_seconds() -> float:
    raw = os.getenv("THREE_POLICY_PROCESS_TIMEOUT_SECONDS")
    if raw is None:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        return max(0.01, float(raw))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def invoke(path: str, periphery: Any) -> list[Any]:
    """Return wire outcome ``[1, next]`` or ``[0, error]``.

    Only the plastic periphery crosses into the child process.  The caller
    translates the numeric wire tag into the MeTTa ``success``/``failure``
    outcome and applies the two-equation process kernel.
    """

    try:
        process_path = Path(path).resolve(strict=True)
    except BaseException as error:
        return [0, f"Process resolution failed: {type(error).__name__}: {error}"]
    with tempfile.TemporaryDirectory(prefix="three-policy-process-") as directory:
        temporary = Path(directory)
        payload_path = temporary / "payload.json"
        result_path = temporary / "result.json"
        try:
            payload_path.write_text(
                json.dumps(periphery, ensure_ascii=False), encoding="utf-8"
            )
        except BaseException as error:
            return [0, f"Payload serialization failed: {type(error).__name__}: {error}"]

        child = subprocess.Popen(
            [
                os.getenv("THREE_POLICY_PYTHON")
                or shutil.which("python3")
                or sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                str(process_path),
                str(payload_path),
                str(result_path),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        try:
            child.wait(timeout=_timeout_seconds())
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
            return [0, "TIMEOUT"]

        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except BaseException:
            return [0, f"Process exited with code {child.returncode} without a result"]
        if result.get("ok") is True and "next" in result:
            return [1, result["next"]]
        return [0, str(result.get("error", "invalid process result"))]


if __name__ == "__main__":
    if len(sys.argv) != 5 or sys.argv[1] != "--worker":
        raise SystemExit("process_host.py --worker PROCESS PAYLOAD RESULT")
    _worker(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
