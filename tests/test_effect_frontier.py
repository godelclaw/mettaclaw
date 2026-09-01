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
    def assert_corrupt_shadow_is_rejected(self, selector):
        environment = {"METTACLAW_EFFECT_BACKEND_STATE": "/shadow/state"}
        if selector is not None:
            environment["METTACLAW_EFFECT_BACKEND"] = selector
        live = types.SimpleNamespace(
            begin_effect_turn=lambda _turn: self.fail(
                "corrupt shadow selector reached live provider"
            )
        )
        with mock.patch.dict(
            os.environ, environment, clear=True
        ), mock.patch.dict(sys.modules, {"telegram": live}):
            with self.assertRaisesRegex(
                RuntimeError, "inconsistent effect backend configuration"
            ):
                effect_frontier.begin("turn-corrupt")

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

    def test_shadow_state_never_falls_through_on_selector_corruption(self):
        for selector in (None, "", "tmux_shadow", "TMUX-SHADOW",
                         "tmux-shadow "):
            with self.subTest(selector=selector):
                self.assert_corrupt_shadow_is_rejected(selector)

    def test_removing_selector_guard_makes_corruption_test_red(self):
        with mock.patch.object(
            effect_frontier, "selected_backend", return_value="live"
        ):
            with self.assertRaises(AssertionError):
                self.assert_corrupt_shadow_is_rejected("tmux_shadow")


if __name__ == "__main__":
    unittest.main(verbosity=2)
