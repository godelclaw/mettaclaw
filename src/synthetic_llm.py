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


# --- provider routing --------------------------------------------------------
# Optional second provider: model names starting with "claude-" are served by
# Anthropic's OpenAI-compatible endpoint using ANTHROPIC_API_KEY. Every other
# model takes the synthetic path exactly as before. Switching is session-level
# via set_model(), so the configured default provider is untouched.

_ANTHROPIC_DEFAULT_BASE = "https://api.anthropic.com/v1"
_ANTHROPIC_DEFAULT_MODELS = (
    "claude-fable-5,claude-opus-4-8,claude-sonnet-5,claude-haiku-4-5-20251001"
)


def _is_anthropic_model(name):
    return str(name).strip().startswith("claude-")


# --- model persistence --------------------------------------------------------
# The active model is durable state: a switch (set_model / the /model command)
# writes it here, and process start restores it. Restarts therefore NEVER
# change the model; the config default applies only when no choice was ever
# made. This is a cost-safety property: an expensive model can only ever be
# active by explicit choice.

def _model_state_path():
    default = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "memory", "persistent.metta")
    return os.environ.get("METTACLAW_MODEL_STATE_PATH", default)


_ACTIVE_MODEL_RE = None


import threading

_persist_lock = threading.Lock()


def _persist_model(name):
    """Durably store the choice as an (active-model ...) atom in the agent's
    standing persistent-state file, preserving any other atoms living there.
    Returns True only when the write landed; callers must not activate a
    model whose persistence failed."""
    with _persist_lock:
        return _persist_model_locked(name)


def _persist_model_locked(name):
    try:
        import re as _re
        path = _model_state_path()
        try:
            with open(path, encoding="utf-8") as fh:
                lines = [l for l in fh.read().splitlines()
                         if not _re.match(r"\s*\(active-model\s", l)]
        except OSError:
            lines = []
        lines.append(f"(active-model {str(name).strip()})")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        os.replace(tmp, path)
        return True
    except OSError as exc:
        print(f"[synthetic_llm] could not persist model choice: {exc}",
              file=sys.stderr)
        return False


def _restore_persisted_model():
    try:
        import re as _re
        with open(_model_state_path(), encoding="utf-8") as fh:
            m = _re.search(r"^\s*\(active-model\s+([^\s()]+)\s*\)",
                           fh.read(), _re.M)
        if m:
            os.environ["SYNTHETIC_MODEL"] = m.group(1)
    except OSError:
        pass


_restore_persisted_model()


def _anthropic_models():
    raw = os.environ.get("ANTHROPIC_MODELS", _ANTHROPIC_DEFAULT_MODELS)
    return [m.strip() for m in raw.split(",") if m.strip()]


def _provider_for(model):
    if _is_anthropic_model(model):
        return {
            "name": "anthropic",
            "base": os.environ.get(
                "ANTHROPIC_BASE_URL", _ANTHROPIC_DEFAULT_BASE).rstrip("/"),
            "key": os.environ.get("ANTHROPIC_API_KEY", ""),
        }
    return {
        "name": "synthetic",
        "base": os.environ.get(
            "SYNTHETIC_BASE_URL",
            "https://api.synthetic.new/openai/v1").rstrip("/"),
        "key": os.environ.get("SYNTHETIC_API_KEY", ""),
    }


def _anthropic_request(provider, effective_model, max_tokens, prompt):
    """Native Messages API request with automatic prompt caching.

    The agent context has a stable head (PROMPT/SKILLS/OUTPUT_FORMAT) before
    the per-turn fields; splitting at ' LOOPS_LEFT: ' puts that head in the
    system block, so the top-level cache_control gets cache hits on every
    turn inside a burst (5-minute TTL)."""
    text = str(prompt)
    marker = " LOOPS_LEFT: "
    cut = text.find(marker)
    if cut > 0:
        system, user = text[:cut], text[cut:]
    else:
        system, user = "", text
    body = {
        "model": effective_model,
        "max_tokens": int(max_tokens),
        "messages": [{"role": "user", "content": user}],
    }
    if system:
        # Explicit breakpoint on the stable head only: the per-turn user
        # message is rebuilt every call, so automatic (top-level) caching
        # would cache system+user and never hit. Verified empirically.
        body["system"] = [{"type": "text", "text": system,
                           "cache_control": {"type": "ephemeral"}}]
    return urllib.request.Request(
        provider["base"] + "/messages",
        json.dumps(body).encode("utf-8"),
        {
            "x-api-key": provider["key"],
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
    )


def _extract_content(payload):
    """Assistant text from either response dialect (native or openai-compat)."""
    if isinstance(payload.get("content"), list):  # native Messages API
        parts = [b.get("text", "") for b in payload["content"]
                 if isinstance(b, dict) and b.get("type") == "text"]
        usage = payload.get("usage") or {}
        if usage:
            print(
                "[synthetic_llm] anthropic usage: "
                f"in={usage.get('input_tokens')} "
                f"cache_read={usage.get('cache_read_input_tokens')} "
                f"cache_write={usage.get('cache_creation_input_tokens')} "
                f"out={usage.get('output_tokens')}",
                file=sys.stderr,
            )
        return "".join(parts)
    return payload["choices"][0]["message"]["content"]


def chat(model, max_tokens, effort, prompt):
    effective_model = os.environ.get("SYNTHETIC_MODEL", str(model))
    provider = _provider_for(effective_model)
    key = provider["key"]
    if not key:
        if provider["name"] == "anthropic":
            # A session-switched provider must never crash the loop.
            return _empty_action("ANTHROPIC_API_KEY is not set")
        raise RuntimeError("SYNTHETIC_API_KEY is not set")
    if provider["name"] == "anthropic":
        req = _anthropic_request(provider, effective_model, max_tokens, prompt)
    else:
        data = json.dumps(
            {
                "model": effective_model,
                "messages": [{"role": "user", "content": str(prompt)}],
                "max_tokens": int(max_tokens),
                "reasoning": {"effort": str(effort)},
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            provider["base"] + "/chat/completions",
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
            content = _extract_content(payload)
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


# Operator introspection (models/quota) runs on the poll thread, so a slow
# provider must never hold the channel hostage: 8s, then report the timeout.
_INTROSPECT_TIMEOUT = float(os.environ.get("SYNTHETIC_INTROSPECT_TIMEOUT", "8"))


def _get_json(url):
    key = os.environ.get("SYNTHETIC_API_KEY", "")
    if not key:
        return {"error": "SYNTHETIC_API_KEY is not set"}
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=_INTROSPECT_TIMEOUT) as response:
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
    if _is_anthropic_model(current_model()):
        parts.append("provider=anthropic (its usage is tracked in the Anthropic console; credits below are synthetic's)")
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
    if os.environ.get("ANTHROPIC_API_KEY", ""):
        items.extend(f"({m} provider anthropic)" for m in _anthropic_models())
    return "(" + " ".join(items) + ")" if items else "(no models returned)"


def _synthetic_model_ids():
    data = _get_json(_openai_base() + "/models")
    if "error" in data:
        return []
    return [m.get("id") for m in data.get("data") or []
            if isinstance(m, dict) and m.get("id")]


_MODEL_IDS_CACHE = {"at": 0.0, "ids": []}


def model_ids():
    """Structured list of switchable model ids (synthetic live list plus the
    anthropic allowlist when configured). Presentation belongs to callers.

    Cached for 60s: one operator button press otherwise costs three separate
    round trips to the provider (validate, then rebuild the menu, then the
    next press), which is the difference between a control that feels
    instant and one that feels broken."""
    import time as _time
    if _MODEL_IDS_CACHE["ids"] and _time.time() - _MODEL_IDS_CACHE["at"] < 60:
        return list(_MODEL_IDS_CACHE["ids"])
    ids = list(_synthetic_model_ids())
    if os.environ.get("ANTHROPIC_API_KEY", ""):
        ids.extend(_anthropic_models())
    if ids:
        import time as _time
        _MODEL_IDS_CACHE["at"], _MODEL_IDS_CACHE["ids"] = _time.time(), list(ids)
    return ids


def set_model(name):
    """Switch the model for subsequent chat() calls.

    Validated first, then durably persisted, then activated — a switch that
    cannot be persisted is not applied. The choice survives restarts.
    """
    name = str(name).strip()
    if _is_anthropic_model(name):
        if not os.environ.get("ANTHROPIC_API_KEY", ""):
            return ("anthropic provider not configured "
                    "(ANTHROPIC_API_KEY missing); model unchanged")
        if name not in _anthropic_models():
            return (f"unknown anthropic model '{name}'; available: "
                    + ", ".join(_anthropic_models()))
        if not _persist_model(name):
            return (f"switch to '{name}' NOT applied: could not durably "
                    "persist the choice")
        os.environ["SYNTHETIC_MODEL"] = name
        return f"model set to '{name}' (anthropic); persists across restarts"
    data = _get_json(_openai_base() + "/models")
    if "error" in data:
        return f"cannot validate model list ({data['error']}); model unchanged"
    valid = [m.get("id") for m in data.get("data") or [] if isinstance(m, dict) and m.get("id")]
    if not valid:
        return "model list empty; model unchanged"
    if name not in valid:
        return f"unknown model '{name}'; available: {', '.join(str(v) for v in valid)}"
    if not _persist_model(name):
        return (f"switch to '{name}' NOT applied: could not durably persist "
                "the choice")
    os.environ["SYNTHETIC_MODEL"] = name
    return f"model set to '{name}'; persists across restarts"
