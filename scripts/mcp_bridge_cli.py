#!/usr/bin/env python3
"""CLI shim around CeTTaClaw's MCP SDK bridge.

The bridge implementation is vendored alongside this file (scripts/mcp_bridge.py)
This file adapts the bridge to a process/stdin boundary:

  mcp_bridge_cli.py servers
  mcp_bridge_cli.py tools SERVER
  mcp_bridge_cli.py tool-info SERVER TOOL
  mcp_bridge_cli.py call SERVER TOOL   # JSON object read from stdin

The bridge itself reads .mcp.json using METTACLAW_MCP_CONFIG/MCP_CONFIG_PATH
or the same parent-walk fallback as Pettaclaw.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys


def _json(data: object) -> str:
    return json.dumps(data, ensure_ascii=True, sort_keys=True)


def _error(message: object) -> str:
    return _json({"error": str(message)})


def _load_bridge():
    # Default to the vendored bridge sibling; METTACLAW_MCP_BRIDGE overrides it
    # (an empty value falls back to the sibling, so callers may pass "" safely).
    default = Path(__file__).resolve().parent / "mcp_bridge.py"
    path = Path(os.environ.get("METTACLAW_MCP_BRIDGE") or str(default)).expanduser()
    spec = importlib.util.spec_from_file_location("pettaclaw_mcp_bridge", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load MCP bridge from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(_error("usage: mcp_bridge_cli.py servers|tools|tool-info|call ..."))
        return 2

    try:
        bridge = _load_bridge()
        op = argv[1]
        if op == "servers" and len(argv) == 2:
            print(bridge.servers())
            return 0
        if op == "tools" and len(argv) == 3:
            print(bridge.tools(argv[2]))
            return 0
        if op == "tool-info" and len(argv) == 4:
            print(bridge.tool_info(argv[2], argv[3]))
            return 0
        if op == "call" and len(argv) == 4:
            arguments_json = sys.stdin.read() or "{}"
            print(bridge.call_tool(argv[2], argv[3], arguments_json))
            return 0
        print(_error(f"bad arguments for {op!r}"))
        return 2
    except Exception as exc:
        print(_error(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
