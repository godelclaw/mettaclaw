#!/usr/bin/env python3
"""Hermetic MCP CLI fixture for the CeTTa adapter's offline contract."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys


TOOL = {
    "name": "echo",
    "description": "Echo text",
    "inputSchema": {
        "type": "object",
        "properties": {"text": {"type": "string"}},
    },
}


def emit(value: object) -> None:
    print(json.dumps(value, ensure_ascii=True, sort_keys=True))


def fail(message: object) -> int:
    emit({"error": str(message)})
    return 1


def configured_servers() -> dict[str, object]:
    path = os.environ.get("METTACLAW_MCP_CONFIG", "")
    if not path:
        raise ValueError("METTACLAW_MCP_CONFIG is required")
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        raise ValueError("mcpServers must be an object")
    return servers


def main(argv: list[str]) -> int:
    try:
        servers = configured_servers()
        if len(argv) == 2 and argv[1] == "servers":
            emit(
                {
                    "servers": [
                        {
                            "name": name,
                            "type": str(spec.get("type", "stdio")),
                        }
                        for name, spec in sorted(servers.items())
                        if isinstance(spec, dict)
                    ]
                }
            )
            return 0

        if len(argv) < 3 or argv[2] not in servers:
            return fail("unknown server")
        if argv[1] == "tools" and len(argv) == 3:
            emit(
                {
                    "server": argv[2],
                    "tools": [
                        {
                            "name": TOOL["name"],
                            "description": TOOL["description"],
                        }
                    ],
                }
            )
            return 0
        if argv[1] == "tool-info" and len(argv) == 4 and argv[3] == "echo":
            emit(TOOL)
            return 0
        if argv[1] == "call" and len(argv) == 4 and argv[3] == "echo":
            arguments = json.loads(sys.stdin.read() or "{}")
            if not isinstance(arguments, dict):
                return fail("arguments must be an object")
            emit(
                {
                    "content": [
                        {
                            "type": "text",
                            "text": "echo:" + str(arguments.get("text", "")),
                        }
                    ],
                    "isError": False,
                }
            )
            return 0
        return fail("bad arguments")
    except Exception as exc:
        return fail(exc)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
