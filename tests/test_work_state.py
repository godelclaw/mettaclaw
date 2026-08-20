"""Work state, derived rather than maintained — so it cannot rot.

Every running digest this project has tried before — MIDTERMMEMORY,
vericore-memory.json, the SQLite store, and the pin file — died the same
way: it needed the agent to choose to refresh it. This one is computed on
read from the goal file the kernel already maintains at every wake, so
there is nothing to remember to do.
"""

import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import goals  # noqa: E402
import helper  # noqa: E402


GOAL = ('(goal {name} {area} sti:{sti} lti:0.5 vibes:(v) blocked-by:{blocked} '
        'last-verified:{verified} note:"{note}")')


class WorkStateTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = pathlib.Path(self.temporary.name) / "goals.metta"
        helper._change_marks.clear()

    def write(self, *records, compost=()):
        self.path.write_text("(goal-budget 3)\n" + "\n".join(records) + "\n",
                             encoding="utf-8")
        if compost:
            (self.path.parent / "goals_compost.log").write_text(
                "\n".join(compost) + "\n", encoding="utf-8")
        return str(self.path)

    def goal(self, name, sti="0.5", blocked="none", verified="never", note="n"):
        return GOAL.format(name=name, area="Axis", sti=sti, blocked=blocked,
                           verified=verified, note=note)

    def test_sections_are_the_handoff_shape(self):
        view = goals.work_state_view(self.write(self.goal("a")))
        for section in ("Active", "Blocked:", "Completed:"):
            self.assertIn(section, view)

    def test_blocked_goals_are_separated_and_name_their_blocker(self):
        view = goals.work_state_view(self.write(
            self.goal("running"), self.goal("waiting", blocked="lila-review")))
        active, blocked = view.index("Active"), view.index("Blocked:")
        self.assertLess(active, view.index("running"))
        self.assertLess(blocked, view.index("waiting"))
        self.assertLess(view.index("running"), blocked)
        self.assertIn("blocked-by:lila-review", view)

    def test_no_priority_is_claimed_from_a_collapsed_signal(self):
        """STI decays to a rounding floor with no source, so ranking by it
        would present an arbitrary order as a decision. Choosing what to do
        next is the reader's job."""
        view = goals.work_state_view(self.write(
            self.goal("low", sti="0.0009"), self.goal("high", sti="0.9")))
        self.assertNotIn("Next Move", view)

    def test_the_ordering_label_does_not_claim_verification(self):
        """last-verified is self-reported; the header must not upgrade it."""
        view = goals.work_state_view(self.write(self.goal("a")))
        self.assertIn("self-reported", view)
        self.assertNotIn("most recently verified", view)

    def test_active_is_ordered_by_most_recent_self_report(self):
        view = goals.work_state_view(self.write(
            self.goal("stale", verified="2026-01-01"),
            self.goal("fresh", verified="2026-08-18"),
            self.goal("untouched")))
        self.assertLess(view.index("fresh"), view.index("stale"))
        self.assertLess(view.index("stale"), view.index("untouched"))

    def test_raw_sti_stays_visible_as_data(self):
        view = goals.work_state_view(self.write(self.goal("a", sti="0.42")))
        self.assertIn("sti:0.42", view)

    def test_completed_comes_from_the_compost_log(self):
        view = goals.work_state_view(self.write(
            self.goal("a"),
            compost=["2026-08-11T23:30:55 solved (goal shipped Axis sti:0.0 "
                     "lti:0.3 vibes:() blocked-by:none)"]))
        self.assertIn("shipped", view[view.index("Completed:"):])

    def test_it_is_bounded(self):
        many = [self.goal("g%02d" % i, note="x" * 400) for i in range(40)]
        self.assertLessEqual(len(goals.work_state_view(self.write(*many),
                                                       max_chars=2000)), 2100)

    def test_a_malformed_goal_file_degrades_instead_of_raising(self):
        path = self.write("(goal broken")
        self.assertIn("unavailable", goals.work_state_view(path))


class ChangeMarkTest(unittest.TestCase):
    def setUp(self):
        helper._change_marks.clear()

    def test_first_sight_is_unmarked(self):
        self.assertEqual(helper.change_mark("b", "one"), "")

    def test_a_standing_block_reports_how_long_it_has_stood(self):
        helper.change_mark("b", "same")
        self.assertEqual(helper.change_mark("b", "same"),
                         " (unchanged for 1 turn)")
        self.assertEqual(helper.change_mark("b", "same"),
                         " (unchanged for 2 turns)")

    def test_a_change_resets_and_is_announced(self):
        helper.change_mark("b", "one")
        helper.change_mark("b", "one")
        self.assertEqual(helper.change_mark("b", "two"), " (changed)")
        self.assertEqual(helper.change_mark("b", "two"),
                         " (unchanged for 1 turn)")

    def test_blocks_are_tracked_independently(self):
        helper.change_mark("x", "a")
        helper.change_mark("y", "b")
        self.assertEqual(helper.change_mark("x", "a"), " (unchanged for 1 turn)")
        self.assertEqual(helper.change_mark("y", "b"), " (unchanged for 1 turn)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
