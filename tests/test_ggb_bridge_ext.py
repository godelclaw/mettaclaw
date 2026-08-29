import pathlib
import sys
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import ggb_bridge_ext  # noqa: E402


class GGBTickTests(unittest.TestCase):
    def test_loop_invokes_tick_as_one_nested_python_call(self):
        loop = (ROOT / "src" / "loop.metta").read_text(encoding="utf-8")

        self.assertIn(
            "(py-call (ggb_bridge_ext.ggbTick oruzi $iteration $results))",
            loop,
        )
        self.assertNotIn(
            "(py-call ggb_bridge_ext.ggbTick oruzi $iteration $results)",
            loop,
        )

    def test_tick_records_bounded_iteration_evidence(self):
        with mock.patch.object(
            ggb_bridge_ext, "ggbL3Share", return_value="evidence-7"
        ) as share:
            result = ggb_bridge_ext.ggbTick("oruzi", 264, "x" * 240)

        self.assertEqual(result, "tick:evidence-7")
        args = share.call_args.args
        self.assertEqual(args[0], "oruzi")
        self.assertEqual(args[2:6], ("tick", 0.5, 0.7, "ggb-tick"))
        self.assertEqual(args[7], "self")
        self.assertTrue(args[1].startswith("iteration=264 results="))
        self.assertEqual(len(args[1].split(" results=", 1)[1]), 200)

    def test_tick_names_empty_results(self):
        with mock.patch.object(
            ggb_bridge_ext, "ggbL3Share", return_value="evidence-8"
        ) as share:
            result = ggb_bridge_ext.ggbTick("oruzi", 265, "")

        self.assertEqual(result, "tick:evidence-8")
        self.assertEqual(
            share.call_args.args[1], "iteration=265 results=no-results"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
