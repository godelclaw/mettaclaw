"""Select the activity frontier paired with the active effect provider."""

from __future__ import annotations

import os


def begin(turn):
    if os.environ.get("METTACLAW_EFFECT_BACKEND") == "tmux-shadow":
        import effect_backend
        return effect_backend.begin_turn(turn)
    import telegram
    telegram.begin_effect_turn(turn)
    return "LIVE_EFFECT_TURN_READY"
