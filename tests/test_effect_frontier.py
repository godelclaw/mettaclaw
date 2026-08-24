import os
import pathlib
import sys
import types
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import effect_frontier  # noqa: E402


class EffectFrontierTests(unittest.TestCase):
    def test_live_frontier_uses_channel_epoch(self):
        calls = []
        telegram = types.SimpleNamespace(
            begin_effect_turn=lambda turn: calls.append(("live", turn))
        )
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.dict(
            sys.modules, {"telegram": telegram}
        ):
            self.assertEqual(
                effect_frontier.begin("turn-live"),
                "LIVE_EFFECT_TURN_READY",
            )
        self.assertEqual(calls, [("live", "turn-live")])

    def test_shadow_frontier_uses_provider_epoch(self):
        calls = []
        backend = types.SimpleNamespace(
            begin_turn=lambda turn: calls.append(("shadow", turn)) or "READY"
        )
        with mock.patch.dict(
            os.environ,
            {"METTACLAW_EFFECT_BACKEND": "tmux-shadow"},
            clear=True,
        ), mock.patch.dict(sys.modules, {"effect_backend": backend}):
            self.assertEqual(effect_frontier.begin("turn-shadow"), "READY")
        self.assertEqual(calls, [("shadow", "turn-shadow")])


if __name__ == "__main__":
    unittest.main(verbosity=2)
