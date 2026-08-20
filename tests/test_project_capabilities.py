import pathlib
import sys
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import project_capabilities  # noqa: E402


INVENTORY = """cetta language inventory (--lang driver/front-end):
  he               implemented  Current direct MeTTa/HE evaluator
  ambient          planned  Planned port
  rhocalc          implemented  Strict-core rho-calculus reducer to quiescence
"""


class ProjectCapabilitiesTest(unittest.TestCase):
    def setUp(self):
        project_capabilities._cache.clear()

    def test_parser_uses_only_explicit_inventory_rows(self):
        self.assertEqual(project_capabilities.parse_cetta_inventory(INVENTORY), [
            ("he", "implemented", "Current direct MeTTa/HE evaluator"),
            ("ambient", "planned", "Planned port"),
            ("rhocalc", "implemented",
             "Strict-core rho-calculus reducer to quiescence"),
        ])

    def test_view_exposes_rhocalc_as_witnessed_not_greenfield(self):
        responses = (
            mock.Mock(returncode=0, stdout="cetta 1.4.0-dev (python)\n"),
            mock.Mock(returncode=0, stdout=INVENTORY),
        )
        with mock.patch.object(project_capabilities.engine_modes,
                               "engine_command", return_value=("/cetta",)), \
             mock.patch.object(project_capabilities.os.path, "isfile",
                               return_value=True), \
             mock.patch.object(project_capabilities.os, "stat",
                               return_value=mock.Mock(st_mtime_ns=7,
                                                      st_size=11)), \
             mock.patch.object(project_capabilities.subprocess, "run",
                               side_effect=responses):
            rendered = project_capabilities.view()
        self.assertIn("revision=cetta 1.4.0-dev (python)", rendered)
        self.assertIn("implemented rhocalc", rendered)
        self.assertIn("planned ambient", rendered)
        self.assertRegex(rendered, r"inventory-sha256=[0-9a-f]{16}")

    def test_missing_artifact_is_absent_without_a_probe(self):
        with mock.patch.object(project_capabilities.engine_modes,
                               "engine_command", return_value=("/missing",)), \
             mock.patch.object(project_capabilities.os.path, "isfile",
                               return_value=False), \
             mock.patch.object(project_capabilities.subprocess, "run") as run:
            self.assertIsNone(project_capabilities.view())
        run.assert_not_called()

    def test_failed_probe_is_unavailable_not_an_empty_inventory(self):
        failed = mock.Mock(returncode=2, stdout="")
        with mock.patch.object(project_capabilities.subprocess, "run",
                               return_value=failed):
            with self.assertRaisesRegex(RuntimeError, "probe failed"):
                project_capabilities._run(("/cetta", "--version"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
