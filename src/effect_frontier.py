"""Select the activity frontier paired with the active effect provider."""

from __future__ import annotations

import os


def selected_backend():
    backend = os.environ.get("METTACLAW_EFFECT_BACKEND", "")
    shadow_state = os.environ.get("METTACLAW_EFFECT_BACKEND_STATE", "")
    if backend == "tmux-shadow":
        return "tmux-shadow"
    if backend or shadow_state:
        raise RuntimeError(
            "inconsistent effect backend configuration: selector=%r" % backend
        )
    return "live"


def begin(turn):
    if selected_backend() == "tmux-shadow":
        import effect_backend
        return effect_backend.begin_turn(turn)
    import telegram
    telegram.begin_effect_turn(turn)
    return "LIVE_EFFECT_TURN_READY"
