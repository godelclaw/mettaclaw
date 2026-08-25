import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import project_evidence  # noqa: E402


class ProjectEvidenceTests(unittest.TestCase):
    def test_view_is_regenerated_from_git_and_immutable_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            repo = root / "repo"
            reports = root / "reports" / "demo"
            repo.mkdir()
            reports.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "evidence.txt").write_text("one\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "evidence.txt"],
                           check=True)
            subprocess.run([
                "git", "-C", str(repo), "-c", "user.name=Test",
                "-c", "user.email=test@example.invalid", "commit", "-qm",
                "evidence",
            ], check=True)
            report = reports / "2026-08-25-test.md"
            report.write_text("# Verified finding\n\nEvidence.\n",
                              encoding="utf-8")
            registry = root / "registry.json"
            registry.write_text(json.dumps({
                "schema": 1,
                "projects": [{
                    "id": "demo",
                    "report_namespace": "demo",
                    "checkouts": [{"path": str(repo), "role": "canonical"}],
                }],
            }), encoding="utf-8")
            with mock.patch.dict(os.environ, {
                "METTACLAW_PROJECT_REGISTRY_PATH": str(registry),
                "METTACLAW_REPORTS_ROOT": str(root / "reports"),
            }):
                project_evidence._cache = None
                view = project_evidence.view()
        self.assertIn("PROJECT demo", view)
        self.assertIn("role=canonical", view)
        self.assertIn("tracked-dirty=false", view)
        self.assertIn("report=2026-08-25-test.md", view)
        self.assertIn("title=Verified finding", view)


if __name__ == "__main__":
    unittest.main(verbosity=2)
