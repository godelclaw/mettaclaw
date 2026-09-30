"""Opt-in JSON bridge for MeTTa; importing it does not start a gateway."""

import json
import os

from execution_gateway import Client, GatewayError


def _call(operation, *args, **kwargs):
    try:
        client = Client(os.environ["METTACLAW_GATEWAY_SOCKET"],
                        os.environ["METTACLAW_GATEWAY_AGENT"])
        value = getattr(client, operation)(*args, **kwargs)
        return json.dumps({"ok": True, "value": value})
    except (GatewayError, OSError, KeyError, TypeError, ValueError) as exc:
        return json.dumps({"ok": False, "error":
                           exc.code if isinstance(exc, GatewayError)
                           else type(exc).__name__})


def submit(request_id, tool, arguments_json="[]", input_json="null", timeout_seconds=30):
    try:
        arguments = json.loads(arguments_json)
        value = json.loads(input_json)
        seconds = float(timeout_seconds)
    except (TypeError, ValueError):
        return json.dumps({"ok": False, "error": "invalid-request"})
    return _call("submit", str(request_id), str(tool), arguments, value, seconds)


def status(request_id):
    return _call("status", str(request_id))


def cancel(request_id):
    return _call("cancel", str(request_id))
