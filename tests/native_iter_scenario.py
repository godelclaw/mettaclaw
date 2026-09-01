"""Deterministic state for the native Iter multi-turn runtime probe."""

from __future__ import annotations

import os
from pathlib import Path

import helper
import synthetic_llm


APPEND_TRANSFORM = """\
(= (iter-transform
      (coding-view $messages $advertised))
   (success
     (coding-view
       (coding-message-append-one
         $messages (coding-message user %s))
       $advertised)))
"""

FAIL_TRANSFORM = "(= (iter-transform $visible) failure)\n"

TIMEOUT_TRANSFORM = """\
(= (native-iter-scenario-spin) (native-iter-scenario-spin))
(= (iter-transform $visible) (native-iter-scenario-spin))
"""


_prompts: list[str] = []


def _directory() -> Path:
    return Path(os.environ["METTACLAW_ITER_PROCESS_DIR"])


def _replace_transformations(files: dict[str, str]) -> int:
    directory = _directory()
    directory.mkdir(parents=True, exist_ok=True)
    for path in directory.glob("*.metta"):
        path.unlink()
    for name, source in files.items():
        (directory / name).write_text(source, encoding="utf-8")
    return 1


def select_stage(stage: str) -> int:
    if stage == "first":
        return _replace_transformations({
            "10_first.metta": APPEND_TRANSFORM % "iter-stage-first",
        })
    if stage == "failure":
        return _replace_transformations({
            "10_failure.metta": FAIL_TRANSFORM,
            "20_after_failure.metta": APPEND_TRANSFORM % "iter-stage-second",
        })
    if stage == "timeout":
        return _replace_transformations({
            "10_timeout.metta": TIMEOUT_TRANSFORM,
        })
    if stage == "fourth":
        return _replace_transformations({
            "10_fourth.metta": APPEND_TRANSFORM % "iter-stage-fourth",
        })
    raise ValueError(f"unknown native Iter scenario stage: {stage}")


def _chat(*args) -> str:
    _prompts.append(str(args[-1]))
    responses = (
        "((help send))",
        "((help pin))",
        "((help mode))",
        "((nop))",
    )
    return responses[min(len(_prompts) - 1, len(responses) - 1)]


def install() -> int:
    _prompts.clear()
    synthetic_llm.chat = _chat
    helper._working_boot_cache = {}
    helper.working_boot = lambda: 1
    return 1


def verdict() -> int:
    if len(_prompts) != 4:
        return 0
    first, second, third, fourth = _prompts
    all_prompts = "\n".join(_prompts)
    checks = {
        "persona": all(
            "GODEL_NATIVE_ITER_PERSONA" in prompt for prompt in _prompts),
        "pins": all("GODEL_NATIVE_ITER_PIN" in prompt for prompt in _prompts),
        "first-visible": "user: iter-stage-first" in first,
        "first-is-snapshot": "iter-stage-second" not in first,
        "second-visible": "user: iter-stage-second" in second,
        "second-replaces-first": "iter-stage-first" not in second,
        "failure-observed": "10_failure.metta failure" in second,
        "first-feedback": "usage: (send" in second,
        "timeout-stutters-first": "iter-stage-first" not in third,
        "timeout-stutters-second": "iter-stage-second" not in third,
        "timeout-precedes-fourth": "iter-stage-fourth" not in third,
        "timeout-observed": "10_timeout.metta failure" in third,
        "timeout-detail": "timeout" in third,
        "second-feedback": "usage: (pin" in third,
        "fourth-visible": "user: iter-stage-fourth" in fourth,
        "fourth-replaces-first": "iter-stage-first" not in fourth,
        "fourth-replaces-second": "iter-stage-second" not in fourth,
        "observations-cross-boundary": "ITER_PROCESS_OBSERVATIONS" in all_prompts,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        print("NATIVE_ITER_SCENARIO_FAILED " + " ".join(failed))
        print("NATIVE_ITER_PERSONA_PRESENCE " + repr([
            "GODEL_NATIVE_ITER_PERSONA" in prompt for prompt in _prompts
        ]))
        print("NATIVE_ITER_FIRST_PROMPT " + repr(first[:500]))
    return int(not failed)
