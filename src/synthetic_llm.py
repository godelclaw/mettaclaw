import json
import os
import urllib.request


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
    with urllib.request.urlopen(req, timeout=120) as response:
        payload = json.loads(response.read())
    return payload["choices"][0]["message"]["content"]
