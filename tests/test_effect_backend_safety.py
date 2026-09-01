import os
import pathlib
import sys
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import effect_backend  # noqa: E402
from godel_shadow import FullShadow  # noqa: E402


class EffectBackendMutationTests(unittest.TestCase):
    def environment(self, shadow):
        return mock.patch.dict(os.environ, {
            "METTACLAW_EFFECT_BACKEND": "tmux-shadow",
            "METTACLAW_EFFECT_BACKEND_STATE": str(shadow.state_path),
        }, clear=False)

    def observe(self, shadow, turn):
        effect_backend.begin_turn(turn)
        outcome = effect_backend.dispatch(["tmux-windows"])
        self.assertEqual(outcome[0], "handled")
        return shadow.state()["receipts"]

    def test_removing_receipt_consumption_makes_single_use_red(self):
        with FullShadow() as shadow, self.environment(shadow):
            receipt = next(iter(self.observe(shadow, 1)))
            original = effect_backend._reserve_effect

            def reserve_without_consuming(state, command, identifier):
                stored = state["receipts"][identifier]
                operation = original(state, command, identifier)
                state["receipts"][identifier] = stored
                return operation

            with mock.patch.object(
                effect_backend, "_reserve_effect", reserve_without_consuming
            ):
                effect_backend.begin_turn(2)
                first = effect_backend.dispatch([
                    "tmux-send-observed", receipt, ":",
                ])
                second = effect_backend.dispatch([
                    "tmux-send-observed", receipt, ":",
                ])
            self.assertEqual(first[0], "handled")
            self.assertNotIn(
                "unknown or expired observation receipt", second[1]
            )
            self.assertIn(receipt, shadow.state()["receipts"])

    def test_crash_after_physical_effect_keeps_receipt_nonreplayable(self):
        with FullShadow() as shadow, self.environment(shadow):
            receipts = self.observe(shadow, 1)
            receipt, observed = next(iter(receipts.items()))
            before_effects = shadow.state()["effects"]
            with mock.patch.object(
                effect_backend, "_finish_reserved",
                side_effect=RuntimeError("simulated process death"),
            ):
                effect_backend.begin_turn(2)
                outcome = effect_backend.dispatch([
                    "tmux-send-observed", receipt, ":",
                ])
            state = shadow.state()
            shadow.world.wait_until(
                observed["pane_id"],
                lambda pane: pane.fingerprint != observed["fingerprint"],
                timeout=3.0,
            )
            self.assertIn("SHADOW_ERROR RuntimeError", outcome[1])
            self.assertNotIn(receipt, state["receipts"])
            self.assertEqual(state["effects"], before_effects)
            self.assertEqual(state["trace"][-1]["status"], "reserved")
            self.assertTrue(state["pending_effects"])
            replay = effect_backend.dispatch([
                "tmux-send-observed", receipt, ":",
            ])
            self.assertIn("unknown or expired observation receipt", replay[1])

    def test_removing_write_ahead_reproduces_unrecorded_effect(self):
        with FullShadow(prompt_timeout=0.1) as shadow, self.environment(shadow):
            self.observe(shadow, 1)
            effect_backend.begin_turn(2)
            effect_backend.dispatch([
                "tmux-new-shell-after", "r1", "claude-room",
            ])
            receipts = self.observe(shadow, 3)
            receipt, observed = next(
                (key, value) for key, value in receipts.items()
                if value["window_name"] == "claude-room"
            )
            state = shadow.state()
            state["launch_command"] = "printf NO_TRUST"
            shadow._write_state(state)

            def reserve_nothing(state, _command, _identifier):
                state["operation_serial"] = int(
                    state.get("operation_serial", 0)
                ) + 1
                return state["operation_serial"]

            before = shadow.state()
            with mock.patch.object(
                effect_backend, "_reserve_effect", reserve_nothing
            ):
                effect_backend.begin_turn(4)
                outcome = effect_backend.dispatch([
                    "tmux-send-observed", receipt, "printf NO_TRUST",
                ])
            after = shadow.state()
            screen = shadow.world.wait_for_text(
                observed["pane_id"], "NO_TRUST", timeout=3.0
            ).content
            self.assertIn("NO_TRUST", screen)
            self.assertIn("SHADOW_ERROR StopIteration", outcome[1])
            self.assertEqual(after["effects"], before["effects"])
            self.assertEqual(len(after["trace"]), len(before["trace"]))
            self.assertIn(receipt, after["receipts"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
