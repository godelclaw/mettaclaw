"""Read-only adapters for the live pilot; no shell or network credentials."""

import json
import os
from pathlib import Path
import subprocess
import sys

import fsops


def execute(tool, value):
    if not isinstance(value, dict):
        raise ValueError("tool input must be an object")
    if tool == "project-status":
        if value:
            raise ValueError("project-status takes an empty object")
        def git(*arguments):
            return subprocess.check_output(
                ["git", *arguments], text=True, timeout=3).strip()
        result = {"commit": git("rev-parse", "HEAD"),
                  "branch": git("branch", "--show-current"),
                  "tracked_changes": len(git("status", "--porcelain", "-uno").splitlines())}
    elif tool == "vitals":
        if value:
            raise ValueError("vitals takes an empty object")
        result = {"load": list(os.getloadavg()),
                  "memory": Path("/proc/meminfo").read_text(),
                  "memory_pressure": Path("/proc/pressure/memory").read_text()}
    elif tool == "read-lines":
        if not set(value) <= {"path", "start", "count"} or not isinstance(value.get("path"), str):
            raise ValueError("read-lines needs path, optional start and count")
        result = fsops.read_lines(value["path"], value.get("start", 1), value.get("count", 60))
    elif tool == "ls-tree":
        if not set(value) <= {"path", "depth"} or not isinstance(value.get("path"), str):
            raise ValueError("ls-tree needs path and optional depth")
        result = fsops.ls_tree(value["path"], value.get("depth", 2))
    elif tool == "grep-files":
        if set(value) != {"path", "pattern"} or not all(isinstance(v, str) for v in value.values()):
            raise ValueError("grep-files needs path and pattern")
        result = fsops.grep_files(value["pattern"], value["path"])
    else:
        raise ValueError("unknown read-only tool")
    return {"agent": os.environ["METTACLAW_GATEWAY_AGENT"], "tool": tool, "value": result}


def main():
    if len(sys.argv) != 2:
        raise ValueError("adapter takes exactly one configured tool name")
    print(json.dumps(execute(sys.argv[1], json.load(sys.stdin))))


if __name__ == "__main__":
    main()
