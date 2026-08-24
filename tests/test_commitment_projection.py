import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import commitment_projection  # noqa: E402


class CommitmentProjectionTests(unittest.TestCase):
    def test_missing_provider_is_absent_not_an_invented_phase(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(commitment_projection.view(), "")

    def test_receipt_derived_phase_is_projected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "commitment.json"
            path.write_text(json.dumps({
                "phase": "need-server", "effects": 3, "finished": False,
            }), encoding="utf-8")
            with mock.patch.dict(os.environ, {
                "METTACLAW_COMMITMENT_STATE_PATH": str(path),
            }, clear=False):
                self.assertEqual(
                    commitment_projection.view(),
                    "phase=need-server revision=3 finished=false",
                )

    def test_unknown_phase_is_unavailable_not_laundered(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "commitment.json"
            path.write_text('{"phase":"probably-done"}', encoding="utf-8")
            with mock.patch.dict(os.environ, {
                "METTACLAW_COMMITMENT_STATE_PATH": str(path),
            }, clear=False):
                with self.assertRaises(ValueError):
                    commitment_projection.view()


if __name__ == "__main__":
    unittest.main(verbosity=2)
