import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import context_sources  # noqa: E402


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
        self.assertIn("project-capabilities", ids)
        self.assertEqual(ids[-1], "conversation")


if __name__ == "__main__":
    unittest.main(verbosity=2)
