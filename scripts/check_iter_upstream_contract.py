#!/usr/bin/env python3
"""Witness the hosted Iter reducer against a pinned public Iter revision.

This checker deliberately covers only the transformation contract hosted by
``iter_process_adapter``: sorted entry files, exact successful replacement,
and local stutter on failure.  Iter's memory, channel, pacing, and tool-loop
policies are outside this adapter and therefore outside this check.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any


ITER_REPOSITORY = "https://github.com/patham9/iter.git"
PINNED_REVISION = "f4064d97849ecaccac7939315a3f1a68de15c3ef"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import iter_process_adapter as hosted  # noqa: E402
import iter_authoring as authoring  # noqa: E402


def git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", os.fspath(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def extract_apply_transformation(source: str):
    tree = ast.parse(source, filename="iter.py")
    functions = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "apply_transformation"
    ]
    if len(functions) != 1:
        raise RuntimeError(
            "expected exactly one Iter apply_transformation definition"
        )
    module = ast.Module(body=functions, type_ignores=[])
    namespace: dict[str, Any] = {"Path": Path}

    def invoke_dynamic(path: Path, function: str, *args: Any) -> dict[str, Any]:
        try:
            spec = importlib.util.spec_from_file_location(
                "_iter_contract_" + path.stem, path
            )
            if spec is None or spec.loader is None:
                raise RuntimeError("could not load transformation")
            imported = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(imported)
            return {"ok": True, "result": getattr(imported, function)(*args)}
        except BaseException as error:
            return {
                "ok": False,
                "error": f"{type(error).__name__}: {error}",
            }

    namespace["invoke_dynamic"] = invoke_dynamic
    exec(compile(module, "iter.py", "exec"), namespace)
    return namespace["apply_transformation"]


def write_fixture(directory: Path, name: str, source: str) -> None:
    (directory / name).write_text(source, encoding="utf-8")


def compare_reducers(upstream_apply) -> None:
    with tempfile.TemporaryDirectory(prefix="iter-upstream-contract-") as raw:
        root = Path(raw)
        transformations = root / "transformations"
        transformations.mkdir()
        write_fixture(
            transformations,
            "10_append.py",
            "def transform(messages, tools):\n"
            "    return messages + ['a'], tools + ['first']\n",
        )
        write_fixture(
            transformations,
            "20_failure.py",
            "def transform(messages, tools):\n"
            "    raise RuntimeError('witnessed failure')\n",
        )
        write_fixture(
            transformations,
            "30_append.py",
            "def transform(messages, tools):\n"
            "    return messages + ['b'], tools + ['last']\n",
        )
        write_fixture(
            transformations,
            "_ignored.py",
            "raise RuntimeError('private entry must not run')\n",
        )

        previous = Path.cwd()
        try:
            os.chdir(root)
            upstream_messages, upstream_tools, upstream_errors = upstream_apply(
                ["start"], []
            )
        finally:
            os.chdir(previous)

        snapshot, result = hosted.run_directory(
            transformations, ["start"], []
        )
        expected = (["start", "a", "b"], ["first", "last"])
        if (upstream_messages, upstream_tools) != expected:
            raise AssertionError(
                "upstream reducer no longer satisfies the pinned ordered "
                "replace-or-stutter witness"
            )
        if (result.messages, result.tools) != expected:
            raise AssertionError("hosted Iter reducer diverges from the witness")
        if [item.name for item in snapshot.processes] != [
            "10_append.py", "20_failure.py", "30_append.py"
        ]:
            raise AssertionError("hosted process ordering or filtering diverged")
        if [item.status for item in result.observations] != [
            "success", "failure", "success"
        ]:
            raise AssertionError("hosted success/failure trace diverged")
        if "20_failure.py" not in upstream_errors:
            raise AssertionError("upstream failure was not recorded")


def compare_direct_authoring(upstream_apply) -> None:
    """Show that a receipted direct write activates in upstream and hosted Iter."""

    with tempfile.TemporaryDirectory(prefix="iter-upstream-authoring-") as raw:
        root = Path(raw)
        transformations = root / "transformations"
        transformations.mkdir()
        old_directory = os.environ.get("METTACLAW_ITER_PROCESS_DIR")
        previous = Path.cwd()
        try:
            os.environ["METTACLAW_ITER_PROCESS_DIR"] = os.fspath(transformations)
            before = hosted.capture(transformations)
            receipt = json.loads(authoring.write_transformation(
                "10_authored.py",
                "def transform(messages, tools):\n"
                "    return messages + ['authored'], tools\n",
            ))
            after = hosted.capture(transformations)
            os.chdir(root)
            upstream_messages, upstream_tools, upstream_errors = upstream_apply(
                ["start"], []
            )
        finally:
            os.chdir(previous)
            if old_directory is None:
                os.environ.pop("METTACLAW_ITER_PROCESS_DIR", None)
            else:
                os.environ["METTACLAW_ITER_PROCESS_DIR"] = old_directory

        hosted_result = hosted.run(after, ["start"], [])
        if hosted.run(before, ["start"], []).messages != ["start"]:
            raise AssertionError("a direct write changed an already captured request")
        if receipt.get("state") != "installed":
            raise AssertionError("direct authoring did not return an install receipt")
        if receipt.get("before_revision") != before.revision:
            raise AssertionError("authoring receipt did not bind the prior capture")
        if receipt.get("activation_revision") != after.revision:
            raise AssertionError("authoring receipt did not bind the active capture")
        expected = (["start", "authored"], [])
        if (upstream_messages, upstream_tools) != expected or upstream_errors:
            raise AssertionError("upstream Iter did not activate the authored program")
        if (hosted_result.messages, hosted_result.tools) != expected:
            raise AssertionError("hosted Iter diverged after direct authoring")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repository", type=Path)
    parser.add_argument("--ref", default="origin/master")
    parser.add_argument("--expected", default=PINNED_REVISION)
    arguments = parser.parse_args()

    revision = git(arguments.repository, "rev-parse", arguments.ref).strip()
    if revision != arguments.expected:
        raise SystemExit(
            "Iter revision changed: expected %s, observed %s; review the diff, "
            "rerun this witness, and deliberately update the pin"
            % (arguments.expected, revision)
        )
    source = git(
        arguments.repository, "show", f"{arguments.ref}:iter.py"
    )
    upstream_apply = extract_apply_transformation(source)
    compare_reducers(upstream_apply)
    compare_direct_authoring(upstream_apply)
    print(
        "ITER_UPSTREAM_CONTRACT_OK repository=%s revision=%s"
        % (ITER_REPOSITORY, revision)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
