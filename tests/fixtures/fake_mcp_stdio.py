#!/usr/bin/env python3
import json
import sys


def write(message):
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    try:
        request = json.loads(line)
    except json.JSONDecodeError:
        continue

    method = request.get("method")
    request_id = request.get("id")
    if method == "initialize":
        write(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": request.get("params", {}).get(
                        "protocolVersion", "2024-11-05"
                    ),
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fake-mcp", "version": "0"},
                },
            }
        )
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        write(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": [
                        {
                            "name": "echo",
                            "description": "Echo text",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"text": {"type": "string"}},
                            },
                        }
                    ]
                },
            }
        )
    elif method == "tools/call":
        args = request.get("params", {}).get("arguments", {})
        write(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {"type": "text", "text": "echo:" + str(args.get("text", ""))}
                    ],
                    "isError": False,
                },
            }
        )
    elif request_id is not None:
        write(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": "unknown method"},
            }
        )
