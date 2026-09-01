#!/usr/bin/env python3
from pathlib import Path
import shutil
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from tmux_qualification import GuardedResult, IsolatedTmux  # noqa: E402
import run_tmux_qualification  # noqa: E402


@unittest.skipUnless(shutil.which("tmux"), "tmux is not installed")
class TmuxQualificationTests(unittest.TestCase):
    def test_disposable_tmux_qualification_passes(self):
        self.assertEqual(run_tmux_qualification.main(), 0)

    def test_removing_staleness_guard_makes_qualification_red(self):
        def unsafe_send(instance, observed, text):
            instance.unchecked_send(observed.pane_id, text)
            return GuardedResult("sent", "unsafe-mutation")

        with mock.patch.object(IsolatedTmux, "guarded_send", unsafe_send):
            with self.assertRaisesRegex(
                AssertionError,
                "new screen stimulus withholds stale action",
            ):
                run_tmux_qualification.main()


if __name__ == "__main__":
    unittest.main()
