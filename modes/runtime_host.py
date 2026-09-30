"""Production host for the isolated MeTTa loops.

Only lifecycle, provider, filesystem and CWP channel boundaries live here.
The cognitive loops remain in iter/core.metta and Omega/src/loop.metta.
"""
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import cognitive_health
import durable_telegram
import lifecycle
import loop_modes
import synthetic_llm


def root():
    return Path(os.environ["METTACLAW_MODE_RUNTIME"])


def shared():
    return Path(os.environ["METTACLAW_MODE_STATE_ROOT"])


def mode():
    return os.environ["METTACLAW_ACTIVE_LOOP_MODE"]


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp." + str(os.getpid()))
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def record(kind, **fields):
    with (root() / "runtime.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"time": time.time(), "kind": kind,
                                 "mode": mode(), **fields}) + "\n")


def channel():
    return durable_telegram.Channel(
        os.environ["METTACLAW_TELEGRAM_SERVICE_SOCKET"],
        str(shared() / "mode-channel-sequence"))


def direct(action, **fields):
    import socket
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(35)
        connection.connect(os.environ["METTACLAW_MODE_CHANNEL_SOCKET"])
        stream = connection.makefile("rwb")
        stream.write(json.dumps({"action": action, **fields}).encode() + b"\n")
        stream.flush()
        result = json.loads(stream.readline(65537))
    if not result.get("ok"):
        raise RuntimeError("channel failed: " + str(result.get("error")))
    return result["value"]


def gate():
    """Stop/switch only between provider/tool turns; controls stay separate."""
    flag = os.environ.get("METTACLAW_RECYCLE_REQUEST_PATH", "")
    while True:
        if (flag and Path(flag).exists()) or loop_modes.current_mode() != mode():
            record("recycle")
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(0)
        if lifecycle.cognition_enabled():
            return True
        time.sleep(0.25)


def sleep(seconds):
    deadline = time.monotonic() + max(0, float(seconds))
    while True:
        gate()
        left = deadline - time.monotonic()
        if left <= 0:
            return True
        time.sleep(min(left, 0.25))


def receive():
    """Offer input without acknowledging it until the loop saves history.

    The service remains the durable owner. Switching before a checkpoint
    leaves the input pending for whichever mode starts next. Commands and
    menu taps belong exclusively to the independent command responder.
    """
    gate()
    if os.environ.get("METTACLAW_MODE_CHANNEL_SOCKET"):
        return direct("receive")
    offered = []
    texts = []
    client = channel()
    for task, body in client.pending(128):
        value = json.loads(body)
        if value[0] == "command" and value[2] == "/delete":
            client.answer(task, "Message deletion is unavailable in " + mode() + " mode; switch to godelclaw.")
            continue
        if value[0] in ("command", "callback"):
            continue
        if value[0] != "input":
            with (root() / "channel-receipts.jsonl").open("a") as stream:
                stream.write(json.dumps({"task": task, "receipt": value}) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            client.acknowledge(task)
            continue
        update = value[4]
        message = next((update[k] for k in ("message", "edited_message", "channel_post",
                                           "edited_channel_post") if update.get(k)), {})
        text = message.get("text") or message.get("caption") or ""
        chat = str(message.get("chat", {}).get("id", value[1].split(".")[0]))
        sender = message.get("from", {})
        name = sender.get("first_name") or sender.get("username") or "user"
        # Preserve the durable update even for attachment-only messages.
        if not text:
            text = "[attachment received; use the agent attachment tools to inspect it]"
        texts.append(f"[chat {chat}; {name}] {text}")
        offered.append(task)
        atomic(shared() / "mode-reply-route.json", {"chat": chat})
    if offered:
        atomic(root() / "offered-input.json", offered)
        record("input", count=len(offered))
    return "\n".join(texts)


def commit_inputs():
    if os.environ.get("METTACLAW_MODE_CHANNEL_SOCKET"):
        return direct("commit")
    path = root() / "offered-input.json"
    tasks = read_json(path, [])
    if not tasks:
        return True
    remaining = []
    client = channel()
    for task in tasks:
        try:
            client.acknowledge(task)
        except (OSError, durable_telegram.ChannelError):
            remaining.append(task)
    atomic(path, remaining)
    return not remaining


def send(message):
    if os.environ.get("METTACLAW_MODE_CHANNEL_SOCKET"):
        return direct("send", text=str(message))
    route = read_json(shared() / "mode-reply-route.json", {})
    chat = route.get("chat") or os.environ.get("METTACLAW_TELEGRAM_PRIMARY_CHAT_ID", "") or os.environ.get("METTACLAW_TELEGRAM_CHAT_ID", "") or os.environ.get("TELEGRAM_CHAT_ID", "")
    if not chat:
        return "not sent: no reply chat until input arrives"
    chat = str(chat).split(",")[0].strip()
    client = channel()
    key = client.key(chat)
    commands = [["send", piece] for piece in durable_telegram.chunks(str(message))]
    # Keep the intended key/bytes before submission, including service outages.
    outbox = root() / "outbox"
    outbox.mkdir(exist_ok=True)
    intent = outbox / (key + ".json")
    atomic(intent, {"key": key, "commands": commands})
    client.submit(key, commands)
    intent.unlink()
    record("send", characters=len(str(message)))
    return "accepted by durable Telegram service"


def recover_outbox():
    if os.environ.get("METTACLAW_MODE_CHANNEL_SOCKET"):
        return
    for path in sorted((root() / "outbox").glob("*.json")):
        item = read_json(path, None)
        if item:
            channel().submit(item["key"], item["commands"])
            path.unlink()


def boot():
    # Provider failure backoff is operational pacing. Keep mode/stop controls
    # responsive while retaining the existing adapter's backoff durations.
    synthetic_llm.time = SimpleNamespace(**{
        name: (sleep if name == "sleep" else getattr(time, name))
        for name in dir(time) if not name.startswith("_")})
    loop_modes.record_active(mode(), os.getpid(), str(root()))
    recover_outbox()
    record("boot", pid=os.getpid(), engine=os.environ["METTACLAW_ACTIVE_ENGINE"])
    print("[mode-runtime] started " + mode(), flush=True)
    return True


def iter_boundary(*args):
    cognitive_health.turn_settled()
    record("boundary")
    gate()
    return True


class Message:
    def __init__(self, value):
        self.value = value

    def model_dump(self, exclude_none=True):
        return {k: v for k, v in self.value.items() if not exclude_none or v is not None}


class IterClient:
    def __init__(self, **kwargs):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **request):
        gate()
        record("provider-request", protocol="tool-calls")
        payload = provider_request(request)
        choice = payload["choices"][0]
        return SimpleNamespace(choices=[SimpleNamespace(
            message=Message(choice["message"]), finish_reason=choice.get("finish_reason"))])


def provider_request(request):
    """Use the existing owned HTTP adapter, retaining native tool-call JSON."""
    import urllib.request
    selected = synthetic_llm.current_model()
    provider = synthetic_llm._provider_for(selected)
    cognitive_health.expect_turn(mode())
    try:
        if not provider["key"]:
            raise RuntimeError("provider credential is not configured")
        if provider["name"] == "anthropic":
            payload = anthropic_payload(request, selected)
            endpoint = "/messages"
            headers = {"x-api-key": provider["key"], "anthropic-version": "2023-06-01"}
        else:
            payload = {k: v for k, v in request.items() if k not in ("model", "extra_body")}
            payload["model"] = selected
            payload.update(request.get("extra_body", {}))
            endpoint = "/chat/completions"
            headers = {"Authorization": "Bearer " + provider["key"]}
        req = urllib.request.Request(provider["base"] + endpoint,
            json.dumps(payload).encode(), {**headers, "Content-Type": "application/json"})
        cognitive_health.turn_started(provider["name"])
        response = synthetic_llm._request_json(req, synthetic_llm._float_env("SYNTHETIC_TIMEOUT", 120, 1))
        if provider["name"] == "anthropic":
            synthetic_llm._tally_anthropic(response.get("usage", {}))
            response = anthropic_response(response)
        cognitive_health.turn_completed(len(json.dumps(response)))
        record("provider-response", protocol="tool-calls", provider=provider["name"])
        return response
    except Exception as error:
        cognitive_health.turn_failed(type(error).__name__)
        record("provider-error", error=type(error).__name__)
        sleep(15)
        raise RuntimeError("provider failed: " + type(error).__name__) from None


def anthropic_payload(request, model):
    """Translate Iter's structured messages without losing tool-call IDs.

    Anthropic has no tool-role message: all results for one assistant batch
    precede subsequent text in a single user message. Tool policy remains in
    core.metta; recent Claude models reject forced-tool API options.
    """
    messages, system = [], []

    def text_blocks(value):
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [{"type": "text", "text": value}]
        if isinstance(value, list) and all(b.get("type") == "text" for b in value):
            return value
        raise ValueError("unsupported Iter message content at Anthropic boundary")

    for item in request["messages"]:
        role = item["role"]
        if role == "system":
            if messages:
                raise ValueError("system instructions must precede the conversation")
            system.extend(text_blocks(item.get("content")))
            continue
        if role == "tool":
            role = "user"
            blocks = [{"type": "tool_result", "tool_use_id": item["tool_call_id"],
                       "content": item.get("content", "")}]
            if messages and messages[-1]["role"] == "user" and any(
                    b["type"] != "tool_result" for b in messages[-1]["content"]):
                raise ValueError("tool results must precede user text")
        elif role in ("user", "assistant"):
            blocks = text_blocks(item.get("content"))
            reasoning = item.get("reasoning_details", []) if role == "assistant" else []
            if reasoning:
                if not isinstance(reasoning, list) or any(
                        b.get("type") not in ("thinking", "redacted_thinking") for b in reasoning):
                    raise ValueError("unsupported reasoning at Anthropic boundary")
                blocks = reasoning + blocks
            for call in item.get("tool_calls", []):
                if role != "assistant":
                    raise ValueError("tool calls require an assistant message")
                function = call["function"]
                blocks.append({"type": "tool_use", "id": call["id"],
                               "name": function["name"],
                               "input": json.loads(function["arguments"])})
        else:
            raise ValueError("unsupported Iter message role at Anthropic boundary")
        if blocks:
            if messages and messages[-1]["role"] == role:
                messages[-1]["content"].extend(blocks)
            else:
                messages.append({"role": role, "content": blocks})
    tools = []
    for tool in request.get("tools", []):
        function = tool["function"]
        tools.append({"name": function["name"],
                      "description": function.get("description", ""),
                      "input_schema": function["parameters"]})
    payload = {"model": model, "max_tokens": request["max_tokens"],
               "messages": messages, "tools": tools, "tool_choice": {"type": "auto"}}
    if system:
        payload["system"] = system
    return payload


def anthropic_response(response):
    text, calls, reasoning = [], [], []
    for block in response["content"]:
        if block["type"] == "text":
            text.append(block["text"])
        elif block["type"] == "tool_use":
            calls.append({"id": block["id"], "type": "function", "function": {
                "name": block["name"], "arguments": json.dumps(block["input"], ensure_ascii=False)}})
        elif block["type"] in ("thinking", "redacted_thinking"):
            # Keep signatures opaque, using the reasoning field which Iter
            # already checkpoints and later prunes at its context boundary.
            reasoning.append(block)
        else:
            record("unsupported-provider-block", block_type=block["type"])
            raise ValueError("unsupported Anthropic response block")
    message = {"role": "assistant", "content": "".join(text) or None}
    if reasoning:
        message["reasoning_details"] = reasoning
    if calls:
        message["tool_calls"] = calls
    reason = response.get("stop_reason")
    return {"choices": [{"message": message, "finish_reason": {
        "max_tokens": "length", "tool_use": "tool_calls"}.get(reason, "stop")}]}


def install_iter():
    import iter_host
    iter_host.namespace["openai"] = SimpleNamespace(OpenAI=IterClient)
    iter_host.namespace["time"] = SimpleNamespace(sleep=sleep)
    iter_host.namespace["receive"] = receive
    boot()
    return True


def config(key, default):
    overrides = {"commchannel": "telegram", "provider": "Configured",
                 "memoryDirectory": str(root() / "repos/Omega/memory"),
                 "embeddingprovider": "Disabled"}
    if str(key) == "spamShield":
        return str(default).lower() == "true"
    return overrides.get(str(key), default)


def provider(prompt, max_tokens, reasoning):
    gate()
    cognitive_health.expect_turn(mode())
    record("provider-request", protocol="command-text")
    response = synthetic_llm.chat(synthetic_llm.current_model(), max_tokens, reasoning, prompt)
    record("provider-response", protocol="command-text")
    return response


def omega_sleep(seconds):
    commit_inputs()
    cognitive_health.turn_settled()
    record("boundary")
    return sleep(seconds)


def get_prompt(provider):
    return (root() / "repos/Omega/memory/prompt.txt").read_text()


def get_history(limit):
    path = root() / "repos/Omega/memory/history.metta"
    data = path.read_bytes() if path.exists() else b""
    return data[-int(limit):].decode("utf-8", errors="replace") if limit else ""


def append_history(text):
    path = root() / "repos/Omega/memory/history.metta"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(str(text) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    commit_inputs()
    record("checkpoint")
    return "APPEND-FILE-SUCCESS"


def string_replace(text, separators, replacement):
    return "".join(str(replacement) if char in str(separators) else char for char in str(text))


def read_file(path):
    return Path(str(path)).read_text()


def write_file(path, text, append=False):
    target = Path(str(path))
    with target.open("a" if append else "w", encoding="utf-8") as stream:
        stream.write(str(text))
        stream.flush()
        os.fsync(stream.fileno())
    return "verified " + str(target) + ": " + str(target.stat().st_size) + " bytes"


def remember(text):
    with (root() / "remembered.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"time": time.time(), "text": str(text)}) + "\n")
    return "REMEMBER-SUCCESS"


def query(text):
    path = root() / "remembered.jsonl"
    lines = path.read_text().splitlines() if path.exists() else []
    return "\n".join(line for line in lines if str(text).casefold() in line.casefold())[-5000:]


def log(*args):
    # Upstream verbose logging includes entire prompts; retain only event names.
    return True


def noop(*args):
    return True
