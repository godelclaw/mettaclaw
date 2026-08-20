"""The running action window: what this agent's own hands just did.

Contract mirrors vericore's Verus heartbeat_context_policy, which solved the
same problem once already: turns within a limit, the newest one always
preserved, no-op turns excluded from the recency slots, oldest-first order.
"""

import os
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import helper  # noqa: E402


def block(stamp, commands, message=None):
    lines = ['("%s" ' % stamp]
    if message:
        lines.append(' "HUMAN_MESSAGE: " %s' % message)
    lines.append(" %s" % commands)
    return "\n".join(lines) + "\n"


class ActionWindowTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = pathlib.Path(self.temporary.name) / "history.metta"

    def write(self, *blocks):
        self.path.write_text("".join(blocks), encoding="utf-8")
        return os.fspath(self.path)

    def test_recent_turns_within_limit(self):
        path = self.write(*[block("t%02d" % i, '((shell "cmd%d"))' % i)
                            for i in range(20)])
        window = helper.recent_actions(path, limit=5)
        self.assertEqual(window.count("(shell"), 5)

    def test_ordering_is_oldest_first(self):
        path = self.write(block("t1", '((shell "first"))'),
                          block("t2", '((shell "second"))'))
        window = helper.recent_actions(path, limit=8)
        self.assertLess(window.index("first"), window.index("second"))

    def test_noop_turns_do_not_consume_a_slot(self):
        """Six heartbeats each answered with (nop) must not evict real work."""
        path = self.write(block("t0", '((shell "real work"))'),
                          *[block("n%d" % i, "((nop))") for i in range(6)])
        window = helper.recent_actions(path, limit=3)
        self.assertIn("real work", window)
        self.assertNotIn("nop", window)

    def test_newest_turn_is_never_dropped_only_truncated(self):
        path = self.write(block("t1", '((shell "old"))'),
                          block("t2", '((shell "%s"))' % ("x" * 5000)))
        window = helper.recent_actions(path, limit=8, max_chars=800)
        self.assertLessEqual(len(window), 900)
        self.assertIn("t2", window)
        self.assertTrue(window.rstrip().endswith("…"))

    def test_the_inbound_envelope_is_not_repeated_here(self):
        path = self.write(block("t1", '((send "hi"))',
                                message='[telegram update_id="1" chat="x"]'))
        window = helper.recent_actions(path, limit=8)
        self.assertIn("(send", window)
        self.assertNotIn("HUMAN_MESSAGE", window)
        self.assertNotIn("update_id", window)

    def test_missing_or_empty_journal_never_raises(self):
        self.assertIn("no prior actions",
                      helper.recent_actions("/nonexistent/history.metta"))
        self.assertIn("no prior actions", helper.recent_actions(self.write()))

    def test_relevant_files_are_derived_and_most_recent_first(self):
        path = self.write(
            block("t1", '((shell "cat /workspace/old/thing.py"))'),
            block("t2", '((shell "cat /workspace/new/thing.py"))'))
        files = helper.relevant_files(path, limit=8)
        self.assertLess(files.index("/workspace/new/thing.py"),
                        files.index("/workspace/old/thing.py"))

    def test_relevant_files_ignores_prose_with_slashes(self):
        path = self.write(block("t1", '((send "Atomspace/Chroma and vericore/openclaw"))'))
        self.assertEqual(helper.relevant_files(path, limit=8), "(none)")

    def test_relevant_files_are_bounded(self):
        path = self.write(*[block("t%d" % i, '((shell "cat /workspace/f%d.py"))' % i)
                            for i in range(60)])
        self.assertLessEqual(len(helper.relevant_files(path, limit=60, max_paths=25).split()), 25)


if __name__ == "__main__":
    unittest.main(verbosity=2)
