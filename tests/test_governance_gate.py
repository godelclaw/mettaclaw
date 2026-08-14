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
        completed = mock.Mock(stdout='{"gate": "PASS"}')
        with mock.patch.object(ggb_bridge_ext, "GOV_CLI", "/tmp/gate.py"), mock.patch.dict(
            os.environ, {"METTACLAW_PYTHON_EXECUTABLE": "/runtime/python3"}
        ), mock.patch.object(ggb_bridge_ext.subprocess, "run", return_value=completed) as run:
            self.assertEqual(ggb_bridge_ext.ggbGovernanceGate("tick"), "PASS")
        self.assertEqual(run.call_args.args[0][0], "/runtime/python3")

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
