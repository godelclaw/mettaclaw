"""Typed, bounded context views over the agent's authoritative records.

This module is replaceable policy.  It neither changes the event ledger nor
chooses actions; it only names and bounds the views supplied to a model turn.
"""

from dataclasses import dataclass
import os
import threading


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    max_chars: int
    keep_tail: bool = False


@dataclass(frozen=True)
class Observation:
    source_id: str
    status: str
    text: str


SOURCE_SPECS = (
    SourceSpec("work-state", 8000),
    SourceSpec("affect-gestalt", 2000),
    SourceSpec("pins", 6000, True),
    SourceSpec("recent-actions", 12000, True),
    SourceSpec("relevant-files", 4000),
    SourceSpec("conversation", 30000, True),
)


def _clip(text, spec):
    text = str(text)
    if len(text) <= spec.max_chars:
        return text
    if spec.keep_tail:
        return "…\n" + text[-(spec.max_chars - 2):]
    return text[:spec.max_chars - 1] + "…"


class Projector:
    """Admit known/absent/unavailable source observations.

    A temporary loader failure retains the last known projection.  A genuine
    empty result is different: it intentionally clears that source.
    """

    def __init__(self):
        self._known = {}
        self._lock = threading.RLock()

    def observe(self, spec, loader):
        try:
            value = loader()
        except Exception:
            with self._lock:
                previous = self._known.get(spec.source_id)
            if previous is None:
                return Observation(spec.source_id, "unavailable", "")
            return Observation(spec.source_id, "stale-known", previous)

        if value is None or not str(value).strip():
            with self._lock:
                self._known.pop(spec.source_id, None)
            return Observation(spec.source_id, "absent", "")

        text = _clip(value, spec)
        with self._lock:
            self._known[spec.source_id] = text
        return Observation(spec.source_id, "known", text)

    def render(self, sources):
        observations = [self.observe(spec, loader)
                        for spec, loader in sources]
        blocks = []
        for item in observations:
            header = "SOURCE[%s] status=%s" % (
                item.source_id, item.status)
            blocks.append(header + ("\n" + item.text if item.text else ""))
        return "\n\n".join(blocks)


_PROJECTOR = Projector()


def _loaders():
    import goals
    import helper
    import pins
    import telegram

    history = helper.path_from_env(
        "METTACLAW_HISTORY_PATH", "./memory/history.metta")
    turns = helper.int_env("METTACLAW_RECENT_ACTION_TURNS", 12)
    events = helper.int_env("METTACLAW_CONVERSATION_EVENTS", 64)
    return (
        (SOURCE_SPECS[0], goals.work_state_view),
        (SOURCE_SPECS[1], goals.affect_view),
        (SOURCE_SPECS[2], pins.view),
        (SOURCE_SPECS[3],
         lambda: helper.recent_actions(history, limit=turns)),
        (SOURCE_SPECS[4],
         lambda: helper.relevant_files(history, limit=turns)),
        (SOURCE_SPECS[5],
         lambda: telegram.conversation_window(max_events=events)),
    )


def bundle():
    """One ordered context bundle; never raises across the MeTTa boundary."""
    try:
        return _PROJECTOR.render(_loaders())
    except Exception:
        return "SOURCE[context-bundle] status=unavailable"
