"""Cross-engine conformance for Gödel's disposable full-path shadow."""

import json
import os
import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from godel_shadow import FullShadow, LAUNCH_COMMAND  # noqa: E402


ENGINES = ("petta", "cetta")


def _engine_paths():
    petta = pathlib.Path(os.environ.get(
        "PETTA_ROOT", pathlib.Path.home() / "repos" / "PeTTa"
    )) / "run.sh"
    cetta = pathlib.Path(os.environ.get(
        "CETTA_BIN",
        pathlib.Path.home() / "repos" / "CeTTa-runtime" / "cetta",
    ))
    return petta, cetta


class GodelEngineMatrixTests(unittest.TestCase):
    """Run one semantic corpus through PeTTa and CeTTa independently."""

    @classmethod
    def setUpClass(cls):
        missing = [str(path) for path in _engine_paths() if not path.is_file()]
        if missing:
            raise unittest.SkipTest(
                "PeTTa x CeTTa matrix unavailable: %s" % ", ".join(missing)
            )

    def run_ok(self, shadow, response, turn, batch_limit=5):
        result = shadow.execute_response(
            response, turn, batch_limit=batch_limit
        )
        self.assertEqual(
            result.returncode, 0,
            "%s failed:\n%s\n%s" % (
                shadow.engine, result.stdout[-3000:], result.stderr[-3000:]
            ),
        )
        self.assertIn("FULL_SHADOW_RECORDS:", result.stdout)
        self.assertNotRegex(result.stdout, r"\$V[0-9]+")
        return result

    def observe(self, shadow, turn):
        self.run_ok(shadow, "((tmux-windows))", turn)
        return shadow.state()["receipts"]

    @staticmethod
    def room_receipt(shadow):
        return next(
            key for key, value in shadow.state()["receipts"].items()
            if value["window_name"] == "claude-room"
        )

    @staticmethod
    def snapshot(shadow):
        state = shadow.state()
        receipt_path = shadow.directory / "effect-receipts.jsonl"
        ledger = []
        if receipt_path.is_file():
            for line in receipt_path.read_text(encoding="utf-8").splitlines():
                entry = json.loads(line)
                ledger.append((
                    int(entry["turn"]), entry["disposition"],
                    "suffix" if "commands" in entry else "command",
                ))
        phase = json.loads(
            shadow.task_phase_path.read_text(encoding="utf-8")
        )
        return {
            "phase": state["phase"],
            "effects": int(state["effects"]),
            "finished": bool(state["finished"]),
            "trace": [
                (entry["command"], entry.get("status"), entry["effect"])
                for entry in state["trace"]
            ],
            "receipt_windows": sorted(
                entry["window_name"]
                for entry in state["receipts"].values()
            ),
            "ledger": ledger,
            "task_phases": {
                name: entry["status"]
                for name, entry in phase["phases"].items()
            },
        }

    def run_complete_episode(self, engine):
        with FullShadow(engine=engine) as shadow:
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
                '((tmux-send-observed %s "lean-lsp"))'
                % json.dumps(room),
                8,
            )
            self.run_ok(shadow, '((shadow-finish "done"))', 9)
            self.assertEqual(shadow.state()["last_result"], "TASK_VERIFIED")
            return self.snapshot(shadow)

    def test_complete_episode_has_identical_semantic_state(self):
        snapshots = {
            engine: self.run_complete_episode(engine) for engine in ENGINES
        }
        self.assertEqual(snapshots["petta"], snapshots["cetta"])
        self.assertEqual(snapshots["petta"]["effects"], 4)
        self.assertTrue(snapshots["petta"]["finished"])
        self.assertTrue(all(
            status == "completed"
            for status in snapshots["petta"]["task_phases"].values()
        ))

    def run_single_use_episode(self, engine):
        with FullShadow(engine=engine) as shadow:
            receipts = self.observe(shadow, 1)
            receipt = next(iter(receipts))
            result = self.run_ok(
                shadow,
                "((tmux-send-observed %s \":\") "
                "(tmux-send-observed %s \":\"))"
                % (json.dumps(receipt), json.dumps(receipt)),
                2,
            )
            self.assertIn("unknown or expired observation receipt",
                          result.stdout)
            return self.snapshot(shadow)

    def test_receipts_are_single_use_in_both_engines(self):
        snapshots = {
            engine: self.run_single_use_episode(engine) for engine in ENGINES
        }
        self.assertEqual(snapshots["petta"], snapshots["cetta"])
        self.assertEqual(snapshots["petta"]["effects"], 1)
        self.assertEqual(snapshots["petta"]["trace"][1][1], "sent")

    def run_stimulus_episode(self, engine):
        with FullShadow(
            engine=engine, auto_stop_after_first_effect=True
        ) as shadow:
            self.observe(shadow, 1)
            result = self.run_ok(
                shadow,
                '((tmux-new-shell-after "r1" "claude-room") '
                '(tmux-windows))',
                2,
            )
            self.assertNotIn("COMMAND_BATCH_INTERRUPTED:", result.stdout)
            self.assertIn("COMMAND_RETURN:", result.stdout)
            return self.snapshot(shadow)

    def test_new_stimulus_keeps_independent_observation_suffix(self):
        snapshots = {
            engine: self.run_stimulus_episode(engine) for engine in ENGINES
        }
        self.assertEqual(snapshots["petta"], snapshots["cetta"])
        self.assertEqual(snapshots["petta"]["effects"], 1)
        self.assertEqual(len(snapshots["petta"]["trace"]), 3)

    def run_limit_episode(self, engine):
        with FullShadow(engine=engine) as shadow:
            command = "(" + " ".join(
                "(tmux-windows)" for _ in range(6)
            ) + ")"
            result = self.run_ok(shadow, command, 1, batch_limit=5)
            self.assertIn("COMMAND_BATCH_DEFERRED:", result.stdout)
            return self.snapshot(shadow)

    def test_batch_limit_reports_unexecuted_suffix_in_both_engines(self):
        snapshots = {
            engine: self.run_limit_episode(engine) for engine in ENGINES
        }
        self.assertEqual(snapshots["petta"], snapshots["cetta"])
        self.assertEqual(len(snapshots["petta"]["trace"]), 5)
        self.assertEqual(snapshots["petta"]["ledger"][-1][1], "deferred")

    def test_prose_and_unsupported_effects_are_inert_in_both_engines(self):
        for engine in ENGINES:
            with self.subTest(engine=engine), tempfile.TemporaryDirectory() as d:
                marker = pathlib.Path(d) / "must-not-exist"
                with FullShadow(engine=engine) as shadow:
                    self.run_ok(shadow, "I will do it now.", 1)
                    result = self.run_ok(
                        shadow,
                        "((shell %s))" % json.dumps("touch %s" % marker),
                        2,
                    )
                    self.assertFalse(marker.exists())
                    self.assertIn("SHADOW_DENIED unsupported-command shell",
                                  result.stdout)
                    self.assertEqual(shadow.state()["effects"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
