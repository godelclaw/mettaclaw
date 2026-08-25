import pathlib
import os
import sys
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import context_sources  # noqa: E402
import effect_receipts  # noqa: E402


class ContextSourcesTest(unittest.TestCase):
    def setUp(self):
        self.projector = context_sources.Projector()
        self.spec = context_sources.SourceSpec("memory", 12)

    def test_known_value_is_named_and_bounded(self):
        observed = self.projector.observe(self.spec, lambda: "abcdefghijklm")
        self.assertEqual(observed.status, "known")
        self.assertEqual(observed.source_id, "memory")
        self.assertLessEqual(len(observed.text), 12)

    def test_unavailable_preserves_last_known_value(self):
        self.projector.observe(self.spec, lambda: "witnessed")

        def unavailable():
            raise RuntimeError("temporary")

        observed = self.projector.observe(self.spec, unavailable)
        self.assertEqual(observed.status, "stale-known")
        self.assertEqual(observed.text, "witnessed")

    def test_absence_clears_the_previous_projection(self):
        self.projector.observe(self.spec, lambda: "witnessed")
        absent = self.projector.observe(self.spec, lambda: "")
        self.assertEqual(absent.status, "absent")
        unavailable = self.projector.observe(
            self.spec, lambda: (_ for _ in ()).throw(RuntimeError()))
        self.assertEqual(unavailable.status, "unavailable")
        self.assertEqual(unavailable.text, "")

    def test_source_order_and_identity_are_explicit(self):
        first = context_sources.SourceSpec("first", 20)
        second = context_sources.SourceSpec("second", 20)
        rendered = self.projector.render((
            (first, lambda: "one"),
            (second, lambda: "two"),
        ))
        self.assertLess(rendered.index("SOURCE[first]"),
                        rendered.index("SOURCE[second]"))
        self.assertEqual(rendered.count("SOURCE[first]"), 1)
        self.assertEqual(rendered.count("SOURCE[second]"), 1)

    def test_live_registry_has_unique_stable_ids(self):
        ids = [spec.source_id for spec in context_sources.SOURCE_SPECS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("effect-receipts", ids)
        self.assertIn("recent-proposals", ids)
        self.assertNotIn("recent-actions", ids)
        self.assertLess(ids.index("effect-receipts"),
                        ids.index("recent-proposals"))
        self.assertIn("project-capabilities", ids)
        self.assertIn("project-evidence", ids)
        self.assertIn("task-phase", ids)
        self.assertIn("active-query-declaration", ids)
        self.assertEqual(ids[-1], "conversation")

    def test_broker_receipt_crosses_the_real_context_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "receipts.jsonl"
            with mock.patch.dict(os.environ, {
                "METTACLAW_EFFECT_RECEIPT_PATH": str(path),
                "METTACLAW_HISTORY_PATH": str(
                    pathlib.Path(directory) / "history.metta"),
                "METTACLAW_TELEGRAM_LOG_PATH": str(
                    pathlib.Path(directory) / "updates.jsonl"),
            }):
                effect_receipts.record_command(
                    8, "returned", ["send-file", "report.md"],
                    "partial(failed)",
                )
                rendered = context_sources.bundle()
        self.assertTrue(rendered.startswith("CONTEXT_CERTIFICATE "))
        self.assertIn("SOURCE[effect-receipts] status=known", rendered)
        self.assertIn("partial(failed)", rendered)
        self.assertIn("SOURCE[recent-proposals]", rendered)

    def test_bad_optional_query_file_does_not_erase_base_context(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "queries.json"
            path.write_text("not-json", encoding="utf-8")
            with mock.patch.dict(os.environ, {
                "METTACLAW_ACTIVE_QUERIES_PATH": str(path),
                "METTACLAW_HISTORY_PATH": str(
                    pathlib.Path(directory) / "history.metta"),
                "METTACLAW_TELEGRAM_LOG_PATH": str(
                    pathlib.Path(directory) / "updates.jsonl"),
            }):
                rendered = context_sources.bundle()
        certificate_line = rendered.splitlines()[0].partition(" ")[2]
        import json
        certificate = json.loads(certificate_line)
        self.assertIn("operator-stimulus", certificate["active_queries"])
        self.assertRegex(
            rendered,
            r"SOURCE\[active-query-declaration\] "
            r"status=(?:unavailable|stale-known)",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
