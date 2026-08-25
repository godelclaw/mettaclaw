"""Typed, bounded context views over the agent's authoritative records.

This module is replaceable policy.  It neither changes the event ledger nor
chooses actions; it only names and bounds the views supplied to a model turn.
"""

from dataclasses import dataclass
import hashlib
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
    revision: str


SOURCE_SPECS = (
    SourceSpec("work-state", 8000),
    SourceSpec("commitment-state", 2000),
    SourceSpec("task-phase", 3000),
    SourceSpec("active-query-declaration", 3000),
    SourceSpec("affect-gestalt", 2000),
    SourceSpec("pins", 6000, True),
    SourceSpec("effect-receipts", 14000, True),
    SourceSpec("recent-proposals", 10000, True),
    SourceSpec("relevant-files", 4000),
    SourceSpec("project-evidence", 8000),
    SourceSpec("project-capabilities", 5000),
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

    @staticmethod
    def _revision(value):
        return "sha256:" + hashlib.sha256(
            str(value).encode("utf-8", "replace")
        ).hexdigest()

    def observe(self, spec, loader):
        try:
            value = loader()
        except Exception:
            with self._lock:
                previous = self._known.get(spec.source_id)
            if previous is None:
                return Observation(spec.source_id, "unavailable", "", "")
            return Observation(
                spec.source_id, "stale-known", previous.text,
                previous.revision)

        if value is None or not str(value).strip():
            with self._lock:
                self._known.pop(spec.source_id, None)
            return Observation(
                spec.source_id, "absent", "", self._revision(""))

        raw = str(value)
        text = _clip(raw, spec)
        observed = Observation(
            spec.source_id, "known", text, self._revision(raw))
        with self._lock:
            self._known[spec.source_id] = observed
        return observed

    def project(self, sources):
        return tuple(self.observe(spec, loader) for spec, loader in sources)

    @staticmethod
    def render_observations(observations):
        blocks = []
        for item in observations:
            header = "SOURCE[%s] status=%s revision=%s" % (
                item.source_id, item.status, item.revision or "unavailable")
            blocks.append(header + ("\n" + item.text if item.text else ""))
        return "\n\n".join(blocks)

    def render(self, sources):
        return self.render_observations(self.project(sources))


_PROJECTOR = Projector()


def _loaders():
    import active_queries
    import commitment_projection
    import effect_receipts
    import goals
    import helper
    import pins
    import project_evidence
    import project_capabilities
    import task_phase
    import telegram

    history = helper.path_from_env(
        "METTACLAW_HISTORY_PATH", "./memory/history.metta")
    turns = helper.int_env("METTACLAW_RECENT_ACTION_TURNS", 12)
    events = helper.int_env("METTACLAW_CONVERSATION_EVENTS", 64)
    return (
        (SOURCE_SPECS[0], goals.work_state_view),
        (SOURCE_SPECS[1], commitment_projection.view),
        (SOURCE_SPECS[2], task_phase.view),
        (SOURCE_SPECS[3], active_queries.view),
        (SOURCE_SPECS[4], goals.affect_view),
        (SOURCE_SPECS[5], pins.view),
        (SOURCE_SPECS[6], effect_receipts.view),
        (SOURCE_SPECS[7],
         lambda: helper.recent_actions(history, limit=turns)),
        (SOURCE_SPECS[8],
         lambda: helper.relevant_files(history, limit=turns)),
        (SOURCE_SPECS[9], project_evidence.view),
        (SOURCE_SPECS[10], project_capabilities.view),
        (SOURCE_SPECS[11],
         lambda: telegram.conversation_window(max_events=events)),
    )


def bundle():
    """One ordered context bundle; never raises across the MeTTa boundary."""
    try:
        import active_queries
        import context_certificate
        observations = _PROJECTOR.project(_loaders())
        projection = _PROJECTOR.render_observations(observations)
        certificate = context_certificate.issue(
            observations, active_queries.from_observations(observations),
            projection)
        return context_certificate.render(certificate) + "\n\n" + projection
    except Exception:
        return "SOURCE[context-bundle] status=unavailable"
