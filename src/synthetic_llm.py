import http.client
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request


_RETRIABLE_HTTP_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


def _float_env(name, default, minimum):
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return max(value, minimum)


def _int_env(name, default, minimum):
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return max(value, minimum)


def _empty_action(reason):
    print(
        "[synthetic_llm] transient chat failure: "
        f"{type(reason).__name__}: {reason}; returning ()",
        file=sys.stderr,
    )
    return "()"


def chat(model, max_tokens, effort, prompt):
    key = os.environ.get("SYNTHETIC_API_KEY", "")
    if not key:
        raise RuntimeError("SYNTHETIC_API_KEY is not set")
    data = json.dumps(
        {
            "model": os.environ.get("SYNTHETIC_MODEL", str(model)),
            "messages": [{"role": "user", "content": str(prompt)}],
            "max_tokens": int(max_tokens),
            "reasoning": {"effort": str(effort)},
        }
    ).encode("utf-8")
    base_url = os.environ.get("SYNTHETIC_BASE_URL", "https://api.synthetic.new/openai/v1")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data,
        {
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
        },
    )
    timeout = _float_env("SYNTHETIC_TIMEOUT", 120.0, 1.0)
    retries = _int_env("SYNTHETIC_RETRIES", 6, 0)
    delay = _float_env("SYNTHETIC_RETRY_DELAY", 2.0, 0.0)
    last_error = None
    for attempt in range(retries + 1):
        retry_after = None
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                payload = json.loads(response.read())
            content = payload["choices"][0]["message"]["content"]
            if isinstance(content, str) and content.strip():
                return content
            return _empty_action("empty response")
        except urllib.error.HTTPError as exc:
            if exc.code not in _RETRIABLE_HTTP_STATUS:
                raise
            last_error = exc
            if exc.headers is not None:
                retry_after = exc.headers.get("Retry-After")
        except (
            TimeoutError,
            socket.timeout,
            urllib.error.URLError,
            ConnectionError,
            http.client.HTTPException,
        ) as exc:
            last_error = exc
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            last_error = exc
        if attempt < retries:
            # Exponential backoff (delay * 2^attempt, capped at 64s): quick
            # retries absorb transient rate limits; the long tail idles politely
            # through credit outages instead of hammering the API. A server
            # Retry-After wins when it asks for longer.
            wait = delay * (2 ** attempt)
            if retry_after is not None:
                try:
                    wait = max(wait, float(retry_after))
                except (TypeError, ValueError):
                    pass
            time.sleep(min(64.0, wait))
    return _empty_action(last_error)


# --- API introspection: quota, models, model switching ------------------------
# These never raise across the Janus boundary (same discipline as chat()).

def _api_root():
    base = os.environ.get("SYNTHETIC_BASE_URL", "https://api.synthetic.new/openai/v1")
    return base.split("/openai/")[0].rstrip("/")


def _openai_base():
    return os.environ.get("SYNTHETIC_BASE_URL", "https://api.synthetic.new/openai/v1").rstrip("/")


def _get_json(url):
    key = os.environ.get("SYNTHETIC_API_KEY", "")
    if not key:
        return {"error": "SYNTHETIC_API_KEY is not set"}
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read())
        return data if isinstance(data, dict) else {"error": "unexpected response"}
    except urllib.error.HTTPError as exc:
        return {"error": f"HTTP {exc.code}"}
    except (
        TimeoutError,
        socket.timeout,
        urllib.error.URLError,
        ConnectionError,
        http.client.HTTPException,
    ) as exc:
        return {"error": type(exc).__name__}
    except (json.JSONDecodeError, ValueError) as exc:
        return {"error": f"bad response: {type(exc).__name__}"}


def current_model():
    return os.environ.get("SYNTHETIC_MODEL", "syn:large:text")


def _percent(value):
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return "?"


def quota():
    """Compact budget summary: current model, weekly credits, rolling 5h window."""
    data = _get_json(_api_root() + "/v2/quotas")
    if "error" in data:
        return f"quota unavailable: {data['error']}"
    parts = [f"model={current_model()}"]
    week = data.get("weeklyTokenLimit") or {}
    if week:
        parts.append(
            f"weekly_credits={week.get('remainingCredits', '?')} of {week.get('maxCredits', '?')} "
            f"({_percent(week.get('percentRemaining'))}% left)"
        )
    five = data.get("rollingFiveHourLimit") or {}
    if five:
        parts.append(
            f"5h_window={five.get('remaining', '?')}/{five.get('max', '?')}"
            + (" LIMITED" if five.get("limited") else "")
        )
    sub = data.get("subscription") or {}
    if sub:
        parts.append(f"subscription={sub.get('requests', '?')}/{sub.get('limit', '?')}")
    return " | ".join(parts)


def models():
    """Available model ids + context length, as a MeTTa-friendly list string."""
    data = _get_json(_openai_base() + "/models")
    if "error" in data:
        return f"models unavailable: {data['error']}"
    items = []
    for model in data.get("data") or []:
        if not isinstance(model, dict):
            continue
        context = model.get("context_length") or model.get("context_window") or "?"
        items.append(f"({model.get('id', '?')} ctx {context})")
    return "(" + " ".join(items) + ")" if items else "(no models returned)"


def set_model(name):
    """Switch the model for subsequent chat() calls this session.

    Validated against the live model list; reverts to the configured default on
    restart, so it is a safe session-scoped choice, not a permanent config edit.
    """
    name = str(name).strip()
    data = _get_json(_openai_base() + "/models")
    if "error" in data:
        return f"cannot validate model list ({data['error']}); model unchanged"
    valid = [m.get("id") for m in data.get("data") or [] if isinstance(m, dict) and m.get("id")]
    if not valid:
        return "model list empty; model unchanged"
    if name not in valid:
        return f"unknown model '{name}'; available: {', '.join(str(v) for v in valid)}"
    os.environ["SYNTHETIC_MODEL"] = name
    return f"model set to '{name}' for this session (reverts to default on restart)"
