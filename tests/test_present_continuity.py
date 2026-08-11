"""Present-moment continuity (PresentMoment.lean made executable).

The invariant under test: restore ∘ persist = identity on the working
self — a recycle or restart is sleep, not a fresh boot. Plus the valence
fine-tunes that shipped with it (loud empty-file reads) and the
loop-source wiring assertions.
"""

import importlib
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import helper  # noqa: E402
import fsops  # noqa: E402


class WorkingSetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["METTACLAW_WORKING_SET_PATH"] = os.path.join(
            self.tmp.name, "working_set.json")
        importlib.reload(helper)

    def tearDown(self):
        os.environ.pop("METTACLAW_WORKING_SET_PATH", None)
        self.tmp.cleanup()

    def test_roundtrip_restores_the_present_moment(self):
        self.assertEqual(helper.working_set_save(37, 5, "verified L14", 123.5), 1)
        self.assertEqual(helper.working_boot(), 1)
        self.assertEqual(helper.boot_int("loops", 50), 37)
        self.assertEqual(helper.boot_int("sleepInterval", 1), 5)
        self.assertEqual(helper.boot_num("last_heartbeat", 0.0), 123.5)
        woke = helper.boot_str("lastresults", "")
        self.assertIn("CONTINUITY: resumed", woke)
        self.assertIn("verified L14", woke)

    def test_first_boot_keeps_fresh_defaults(self):
        self.assertEqual(helper.working_boot(), 1)
        self.assertEqual(helper.boot_int("loops", 50), 50)
        self.assertEqual(helper.boot_str("lastresults", ""), "")

    def test_corrupt_snapshot_falls_back_to_defaults(self):
        with open(os.environ["METTACLAW_WORKING_SET_PATH"], "w") as fh:
            fh.write("{not json")
        self.assertEqual(helper.working_boot(), 1)
        self.assertEqual(helper.boot_int("loops", 50), 50)

    def test_rest_intent_greets_the_next_waking_exactly_once(self):
        helper.working_set_save(10, 60, "mid-build", 1.0)
        self.assertEqual(helper.intent_save("waiting on the Lean build"), 1)
        helper.working_boot()
        woke = helper.boot_str("lastresults", "")
        self.assertIn("WOKE_FROM_REST: waiting on the Lean build", woke)
        # consumed: a second boot must not replay the intention
        helper.working_boot()
        self.assertNotIn("WOKE_FROM_REST", helper.boot_str("lastresults", ""))

    def test_lastresults_capped_to_feedback_window(self):
        helper.working_set_save(1, 1, "x" * 90000, 0.0)
        helper.working_boot()
        self.assertLessEqual(len(helper.boot_str("lastresults", "")), 50000)


class LoudEmptyReadTests(unittest.TestCase):
    def test_empty_file_reads_loudly_not_blankly(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as fh:
            path = fh.name
        try:
            self.assertIn("READ_OK_EMPTY_FILE", fsops.read_file(path))
            self.assertIn("READ_OK_EMPTY_FILE", fsops.read_lines(path, 1, 10))
        finally:
            os.unlink(path)

    def test_missing_file_still_distinct(self):
        verdict = fsops.read_file("/definitely/not/here.txt")
        self.assertIn("no such file", verdict)
        self.assertNotIn("READ_OK_EMPTY_FILE", verdict)


class LoopWiringTests(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "src", "loop.metta")) as fh:
            self.loop = fh.read()
        with open(os.path.join(ROOT, "src", "skills.metta")) as fh:
            self.skills = fh.read()

    def test_boot_restores_instead_of_blank_arming(self):
        self.assertIn("(helper.working_boot)", self.loop)
        self.assertIn('(helper.boot_int "loops" (maxLoops))', self.loop)
        self.assertIn('(helper.boot_str "lastresults" ""', self.loop)
        # the only unconditional full re-arm left is the heartbeat's own
        self.assertEqual(self.loop.count("(change-state! &loops (maxLoops))"), 1)

    def test_every_turn_boundary_persists(self):
        self.assertIn("(helper.working_set_save", self.loop)

    def test_rest_carries_intention(self):
        self.assertIn("(= (rest $seconds $why)", self.skills)
        self.assertIn("(helper.intent_save", self.skills)


if __name__ == "__main__":
    unittest.main()
