"""Privacy-safe runtime health summary for operators and supervisors."""

import json
import os
import time

import memory_health


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as stream:
            value = json.load(stream)
        return value if isinstance(value, dict) else {}
    except (OSError, TypeError, ValueError):
        return {}


def _health_path():
    configured = os.environ.get("METTACLAW_TELEGRAM_HEALTH_PATH", "")
    if configured:
        return configured
    state_home = os.environ.get(
        "XDG_STATE_HOME", os.path.expanduser("~/.local/state"))
    instance = os.environ.get("METTACLAW_INSTANCE", "default")
    return os.path.join(state_home, "pettaclaw", instance,
                        "telegram-health.json")


def status(now=None):
    now = time.time() if now is None else float(now)
    channel = _read_json(_health_path())
    working = _read_json(os.environ.get(
        "METTACLAW_WORKING_SET_PATH", "memory/working_set.json"))
    poll_at = float(channel.get("last_poll_ok_at", 0) or 0)
    saved_at = float(working.get("saved_at", 0) or 0)
    waiting_until = float(channel.get("waiting_until", 0) or 0)
    legitimate_wait = (channel.get("loop_status") == "waiting"
                       and waiting_until >= now - 10)
    poll_age = None if not poll_at else max(0, int(now - poll_at))
    working_age = None if not saved_at else max(0, int(now - saved_at))
    problems = []
    if channel.get("menu_status") != "ok":
        problems.append("command-menu-not-registered")
    if poll_age is None or poll_age > 120:
        problems.append("telegram-poll-stale")
    if (not legitimate_wait
            and (working_age is None or working_age > 900)):
        problems.append("cognitive-boundary-stale")
    docs, _indexed, behind = memory_health.drift()
    threshold = memory_health.threshold()
    if docs and behind > threshold:
        problems.append("memory-index-drift")
    return {
        "state": "ok" if not problems else "problem",
        "problems": problems,
        "generation": os.environ.get("METTACLAW_DEPLOYED_COMMIT", "unknown")[:12],
        "menu": channel.get("menu_status", "unknown"),
        "telegram_poll_age_seconds": poll_age,
        "loop": "waiting" if legitimate_wait else channel.get(
            "loop_status", "unknown"),
        "working_set_age_seconds": working_age,
        "memories": docs,
        "memory_index_behind": behind,
        "memory_flush_threshold": threshold,
    }


def report():
    value = status()
    problems = ",".join(value["problems"]) or "none"
    return (
        "runtime-health: {state} | generation={generation} | menu={menu} | "
        "telegram-poll-age={poll}s | loop={loop} | working-set-age={working}s | "
        "memory={memories} ({behind}/{threshold} behind) | problems={problems}"
    ).format(
        state=value["state"], generation=value["generation"],
        menu=value["menu"], poll=value["telegram_poll_age_seconds"],
        loop=value["loop"], working=value["working_set_age_seconds"],
        memories=value["memories"], behind=value["memory_index_behind"],
        threshold=value["memory_flush_threshold"], problems=problems,
    )


if __name__ == "__main__":
    print(json.dumps(status(), sort_keys=True))
