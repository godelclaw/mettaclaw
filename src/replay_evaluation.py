"""Evidence-based metrics for historical and simulated agent replays."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Iterable


@dataclass(frozen=True)
class ReplayMetrics:
    redundant_effects: int
    stale_state_actions: int
    lost_commitments: int
    unsupported_claims: int
    context_chars_max: int
    context_chars_total: int
    evidence_recovery_success: float | None
    operator_interruption_latency_ms: float | None

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate(events: Iterable[dict]) -> ReplayMetrics:
    current_revision = None
    successful_effects = set()
    successful_receipts = set()
    phase_status = {}
    redundant = stale = lost = unsupported = 0
    context_sizes = []
    recovered = required = 0
    pending_stimuli = []
    interruption_latencies = []

    for event in events:
        kind = event.get("type")
        if kind == "context":
            current_revision = event.get("evidence_revision")
            context_sizes.append(max(0, int(event.get("context_chars", 0))))
        elif kind == "stimulus":
            current_revision = event.get("evidence_revision", current_revision)
            pending_stimuli.append(float(event.get("at_ms", 0)))
        elif kind == "interrupt" and pending_stimuli:
            started = pending_stimuli.pop(0)
            interruption_latencies.append(max(
                0.0, float(event.get("at_ms", started)) - started
            ))
        elif kind == "effect":
            if (event.get("depends_on_stimulus", True)
                    and current_revision is not None
                    and event.get("issued_revision") != current_revision):
                stale += 1
            if event.get("result") == "success":
                key = str(event.get("effect_key", event.get("action_id", "")))
                if key and key in successful_effects:
                    redundant += 1
                if key:
                    successful_effects.add(key)
                receipt = event.get("receipt")
                if receipt:
                    successful_receipts.add(str(receipt))
        elif kind == "phase":
            phase = str(event.get("phase", ""))
            status = str(event.get("status", "pending"))
            if phase_status.get(phase) == "completed" and status != "completed":
                lost += 1
            if phase:
                phase_status[phase] = status
        elif kind == "claim" and event.get("claim") == "completed":
            support = str(event.get("supported_by", ""))
            if not support or support not in successful_receipts:
                unsupported += 1
        elif kind == "recovery":
            required_sources = set(map(str, event.get("required_sources", [])))
            recovered_sources = set(map(str, event.get("recovered_sources", [])))
            required += len(required_sources)
            recovered += len(required_sources & recovered_sources)

    return ReplayMetrics(
        redundant_effects=redundant,
        stale_state_actions=stale,
        lost_commitments=lost,
        unsupported_claims=unsupported,
        context_chars_max=max(context_sizes, default=0),
        context_chars_total=sum(context_sizes),
        evidence_recovery_success=(recovered / required if required else None),
        operator_interruption_latency_ms=(
            mean(interruption_latencies) if interruption_latencies else None
        ),
    )


def evaluate_file(path: Path) -> ReplayMetrics:
    value = json.loads(path.read_text(encoding="utf-8"))
    events = value.get("events") if isinstance(value, dict) else value
    if not isinstance(events, list):
        raise ValueError("replay must be a list or an object with events")
    return evaluate(events)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("replay", type=Path)
    arguments = parser.parse_args(argv)
    print(json.dumps(
        evaluate_file(arguments.replay).to_dict(),
        ensure_ascii=False, sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
