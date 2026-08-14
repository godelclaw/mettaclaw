import pathlib
import sys
import os
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ggb_bridge_ext


class GovernanceGateBoundaryTests(unittest.TestCase):
    def test_gate_uses_explicit_python_not_embedded_sys_executable(self):
        completed = mock.Mock(stdout='{"gate": "PASS"}', returncode=0)
        with mock.patch.object(ggb_bridge_ext, "GOV_CLI", "/tmp/gate.py"), mock.patch.dict(
            os.environ, {"METTACLAW_PYTHON_EXECUTABLE": "/runtime/python3"}
        ), mock.patch.object(ggb_bridge_ext.subprocess, "run", return_value=completed) as run:
            self.assertEqual(ggb_bridge_ext.ggbGovernanceGate("tick"), "PASS")
        self.assertEqual(run.call_args.args[0][0], "/runtime/python3")

    def test_gate_fails_closed_without_configured_cli(self):
        with mock.patch.object(ggb_bridge_ext, "GOV_CLI", ""), mock.patch.object(
            ggb_bridge_ext.subprocess, "run"
        ) as run:
            self.assertEqual(ggb_bridge_ext.ggbGovernanceGate("tick"), "BLOCK")
        run.assert_not_called()

    def test_gate_fails_closed_on_nonzero_exit_even_if_stdout_says_pass(self):
        completed = mock.Mock(stdout='{"gate": "PASS"}', returncode=7)
        with mock.patch.object(ggb_bridge_ext, "GOV_CLI", "/tmp/gate.py"), mock.patch.object(
            ggb_bridge_ext.subprocess, "run", return_value=completed
        ):
            self.assertEqual(ggb_bridge_ext.ggbGovernanceGate("tick"), "BLOCK")

    def test_gate_fails_closed_on_malformed_or_unknown_verdict(self):
        for stdout in ("not-json", '{"gate": "ALLOW"}', "{}"):
            completed = mock.Mock(stdout=stdout, returncode=0)
            with self.subTest(stdout=stdout), mock.patch.object(
                ggb_bridge_ext, "GOV_CLI", "/tmp/gate.py"
            ), mock.patch.object(
                ggb_bridge_ext.subprocess, "run", return_value=completed
            ):
                self.assertEqual(
                    ggb_bridge_ext.ggbGovernanceGate("tick"), "BLOCK"
                )

    def test_gate_fails_closed_on_subprocess_error(self):
        with mock.patch.object(
            ggb_bridge_ext, "GOV_CLI", "/tmp/gate.py"
        ), mock.patch.object(
            ggb_bridge_ext.subprocess, "run", side_effect=TimeoutError
        ):
            self.assertEqual(ggb_bridge_ext.ggbGovernanceGate("tick"), "BLOCK")

    def test_numeric_predicate_accepts_pass(self):
        with mock.patch.object(
            ggb_bridge_ext, "ggbGovernanceGate", return_value="PASS"
        ):
            self.assertEqual(ggb_bridge_ext.ggbGovernancePassed("tick"), 1)

    def test_numeric_predicate_rejects_every_non_pass_value(self):
        for verdict in ("BLOCK", "", None, "PASS "):
            with self.subTest(verdict=verdict), mock.patch.object(
                ggb_bridge_ext, "ggbGovernanceGate", return_value=verdict
            ):
                self.assertEqual(ggb_bridge_ext.ggbGovernancePassed("tick"), 0)

    def test_loop_uses_numeric_boundary_not_string_or_symbol(self):
        source = (ROOT / "src" / "loop.metta").read_text(encoding="utf-8")
        self.assertIn(
            "(== (py-call (ggb_bridge_ext.ggbGovernancePassed tick)) 1)",
            source,
        )
        self.assertNotIn("(quote PASS)", source)


if __name__ == "__main__":
    unittest.main()
