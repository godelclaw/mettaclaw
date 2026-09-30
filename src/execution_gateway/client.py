"""Small JSON-over-Unix-socket client; no tools or credentials loaded here."""

import json
import socket
import time

MAX_FRAME = 1024 * 1024


class GatewayError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class Client:
    def __init__(self, socket_path, agent, timeout=3):
        self.socket_path = str(socket_path)
        self.agent = agent
        self.timeout = timeout

    def request(self, operation, **fields):
        message = {"version": 1, "agent": self.agent, "operation": operation, **fields}
        payload = (json.dumps(message, allow_nan=False) + "\n").encode()
        if len(payload) > MAX_FRAME:
            raise GatewayError("frame-too-large", "request exceeds the protocol frame")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(self.timeout)
            connection.connect(self.socket_path)
            connection.sendall(payload)
            with connection.makefile("rb") as stream:
                answer = stream.readline(MAX_FRAME + 1)
        if not answer.endswith(b"\n") or len(answer) > MAX_FRAME:
            raise GatewayError("invalid-response", "incomplete or oversized gateway reply")
        reply = json.loads(answer)
        if not isinstance(reply, dict):
            raise GatewayError("invalid-response", "gateway reply must be an object")
        if reply.get("agent") != self.agent:
            raise GatewayError("wrong-agent", "reply belongs to another agent")
        if "error" in reply:
            if not isinstance(reply["error"], dict) or not all(
                    isinstance(reply["error"].get(k), str) for k in ("code", "message")):
                raise GatewayError("invalid-response", "invalid gateway error receipt")
            raise GatewayError(reply["error"]["code"], reply["error"]["message"])
        if "value" not in reply:
            raise GatewayError("invalid-response", "gateway reply has no receipt")
        return reply["value"]

    def submit(self, request_id, tool, arguments=(), input=None, timeout_seconds=30):
        if not isinstance(arguments, (list, tuple)):
            raise GatewayError("invalid-request", "arguments must be a list or tuple")
        return self.request("submit", request={
            "id": request_id, "tool": tool, "arguments": list(arguments),
            "input": input, "deadline": time.time() + timeout_seconds})

    def status(self, request_id):
        return self.request("status", id=request_id)

    def tools(self):
        return self.request("tools")

    def cancel(self, request_id):
        return self.request("cancel", id=request_id)
