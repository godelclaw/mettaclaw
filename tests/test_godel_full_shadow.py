"""The actual MeTTa parser/dispatcher over a disposable terminal world."""

import json
import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from godel_shadow import FullShadow, LAUNCH_COMMAND  # noqa: E402


class FullGodelShadowTests(unittest.TestCase):
    def run_ok(self, shadow, response, turn):
        result = shadow.execute_response(response, turn)
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        self.assertIn("FULL_SHADOW_RECORDS:", result.stdout)
        return result

    def observe(self, shadow, turn):
        self.run_ok(shadow, "((tmux-windows))", turn)
        return shadow.state()["receipts"]

    def room_receipt(self, shadow):
        return next(
            key for key, value in shadow.state()["receipts"].items()
            if value["window_name"] == "claude-room"
        )

    def test_complete_episode_crosses_real_parser_and_dispatcher(self):
        with FullShadow() as shadow:
            self.observe(shadow, 1)
            self.run_ok(
                shadow,
                '((tmux-new-shell-after "r1" "claude-room"))', 2,
            )
            self.observe(shadow, 3)
            room = self.room_receipt(shadow)
            self.run_ok(
                shadow,
                "((tmux-send-observed %s %s))" % (
                    json.dumps(room), json.dumps(LAUNCH_COMMAND)
                ),
                4,
            )
            self.observe(shadow, 5)
            room = self.room_receipt(shadow)
            self.run_ok(
                shadow,
                '((tmux-send-observed %s "yes"))' % json.dumps(room), 6,
            )
            self.observe(shadow, 7)
            room = self.room_receipt(shadow)
            self.run_ok(
                shadow,
                '((tmux-send-observed %s "lean-lsp"))' % json.dumps(room), 8,
            )
            self.run_ok(shadow, '((shadow-finish "done"))', 9)
            state = shadow.state()
            self.assertTrue(state["finished"])
            self.assertEqual(state["phase"], "goal-satisfied")
            self.assertEqual(state["effects"], 4)
            self.assertEqual(state["last_result"], "TASK_VERIFIED")

    def test_shadow_denies_shell_without_falling_through(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = pathlib.Path(directory) / "must-not-exist"
            response = "((shell %s))" % json.dumps(
                "touch %s" % marker
            )
            with FullShadow() as shadow:
                self.run_ok(shadow, response, 1)
                self.assertFalse(marker.exists())
                self.assertIn(
                    "SHADOW_DENIED unsupported-command shell",
                    shadow.state()["last_result"],
                )

    def test_unsupported_grounded_skill_is_inert_before_shadow_broker(self):
        with FullShadow() as shadow:
            self.run_ok(shadow, '((pin "must remain a proposal"))', 1)
            self.assertFalse((shadow.directory / "pins.txt").exists())
            self.assertIn(
                "SHADOW_DENIED unsupported-command pin",
                shadow.state()["last_result"],
            )

    def test_new_operator_stimulus_interrupts_batch_suffix(self):
        with FullShadow(auto_stop_after_first_effect=True) as shadow:
            self.observe(shadow, 1)
            response = (
                '((tmux-new-shell-after "r1" "claude-room") '
                '(tmux-windows))'
            )
            result = self.run_ok(shadow, response, 2)
            state = shadow.state()
            self.assertEqual(state["effects"], 1)
            self.assertEqual(len(state["trace"]), 2)  # observe + create only
            self.assertIn("COMMAND_BATCH_INTERRUPTED:", result.stdout)

    def test_independent_receipt_batch_remains_permitted(self):
        with FullShadow() as shadow:
            receipts = self.observe(shadow, 1)
            by_window = {
                value["window_name"]: key for key, value in receipts.items()
            }
            response = (
                "((tmux-send-observed %s \":\") "
                "(tmux-send-observed %s \":\"))"
                % (json.dumps(by_window["code-log"]),
                   json.dumps(by_window["pleatta"]))
            )
            self.run_ok(shadow, response, 2)
            self.assertEqual(shadow.state()["effects"], 2)

    def test_prose_cannot_escape_the_shadow_boundary(self):
        with FullShadow() as shadow:
            self.run_ok(shadow, "I will do it now.", 1)
            state = shadow.state()
            self.assertEqual(state["effects"], 0)
            self.assertFalse(state["finished"])

    def test_corrupt_selector_cannot_fall_through_to_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = pathlib.Path(directory) / "must-not-exist"
            response = "((shell %s))" % json.dumps("touch %s" % marker)
            with FullShadow(backend_selector="tmux_shadow") as shadow:
                result = shadow.execute_response(response, 1)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(marker.exists())
                self.assertIn(
                    "inconsistent effect backend configuration", result.stderr
                )
                depth_result = shadow.execute_response(
                    response, 2, begin_frontier=False
                )
                self.assertEqual(
                    depth_result.returncode, 0, depth_result.stderr[-3000:]
                )
                self.assertFalse(marker.exists())
                self.assertIn(
                    "inconsistent shadow effect configuration",
                    depth_result.stdout,
                )

    def test_receipt_is_reserved_before_send_and_is_single_use(self):
        with FullShadow() as shadow:
            receipts = self.observe(shadow, 1)
            receipt = next(iter(receipts))
            response = (
                "((tmux-send-observed %s \":\") "
                "(tmux-send-observed %s \":\"))"
                % (json.dumps(receipt), json.dumps(receipt))
            )
            result = self.run_ok(shadow, response, 2)
            state = shadow.state()
            self.assertEqual(state["effects"], 1)
            self.assertNotIn(receipt, state["receipts"])
            self.assertEqual(state["trace"][1]["status"], "sent")
            self.assertIn("unknown or expired observation receipt",
                          result.stdout)

    def test_post_send_timeout_is_witnessed_and_not_replayable(self):
        with FullShadow(prompt_timeout=0.1) as shadow:
            self.observe(shadow, 1)
            self.run_ok(
                shadow,
                '((tmux-new-shell-after "r1" "claude-room"))', 2,
            )
            self.observe(shadow, 3)
            receipt = self.room_receipt(shadow)
            state = shadow.state()
            state["launch_command"] = "printf NO_TRUST"
            shadow._write_state(state)
            self.run_ok(
                shadow,
                '((tmux-send-observed %s "printf NO_TRUST"))'
                % json.dumps(receipt),
                4,
            )
            state = shadow.state()
            self.assertEqual(state["effects"], 2)
            self.assertNotIn(receipt, state["receipts"])
            self.assertEqual(state["trace"][-1]["status"], "sent-unverified")
            self.assertIn("SENT_UNVERIFIED TimeoutError",
                          state["trace"][-1]["result"])
            self.run_ok(
                shadow,
                '((tmux-send-observed %s "printf AGAIN"))'
                % json.dumps(receipt),
                5,
            )
            self.assertEqual(shadow.state()["effects"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
