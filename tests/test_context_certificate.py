import json
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import context_certificate  # noqa: E402
import context_sources  # noqa: E402


class ContextCertificateTests(unittest.TestCase):
    def test_certificate_names_required_fields_and_is_deterministic(self):
        observations = (
            context_sources.Observation("repo", "known", "HEAD a", "sha:a"),
            context_sources.Observation(
                "task-phase", "known", "phase=testing", "sha:p"
            ),
        )
        first = context_certificate.issue(
            observations, ("active-goals", "effect-outcomes"), "projection"
        )
        second = context_certificate.issue(
            observations, ("active-goals", "effect-outcomes"), "projection"
        )
        self.assertEqual(first, second)
        self.assertEqual(first.commitment_phase, "testing")
        rendered = json.loads(
            context_certificate.render(first).partition(" ")[2]
        )
        self.assertEqual(rendered["schema"], 1)
        self.assertIn("evidence_revision", rendered)
        self.assertIn("active_queries", rendered)
        self.assertIn("sources", rendered)
        self.assertIn("projection_receipt", rendered)

    def test_unprojected_evidence_change_changes_revision(self):
        projector = context_sources.Projector()
        spec = context_sources.SourceSpec("bounded", 5)
        left = projector.observe(spec, lambda: "abcdef")
        right = projector.observe(spec, lambda: "abcdeg")
        self.assertEqual(left.text, right.text)
        self.assertNotEqual(left.revision, right.revision)


if __name__ == "__main__":
    unittest.main(verbosity=2)
