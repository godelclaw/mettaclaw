"""The live initializer and disposable shadows share one specialization."""

from __future__ import annotations

import pathlib
import subprocess
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
RENDERER = ROOT / "scripts" / "render_channel_config.py"


class ChannelConfigTests(unittest.TestCase):
    def render(self, kind: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(RENDERER), kind],
            capture_output=True,
            text=True,
        )

    def test_every_supported_channel_is_a_literal_specialization(self):
        for kind in ("telegram", "irc", "mattermost"):
            with self.subTest(kind=kind):
                result = self.render(kind)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(
                    "(configure commchannel %s)" % kind, result.stdout
                )
                self.assertNotIn("$", result.stdout)

    def test_unknown_channel_is_rejected(self):
        result = self.render("invented")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_initializer_delegates_to_the_shared_renderer(self):
        initializer = (ROOT / "initialize.sh").read_text(encoding="utf-8")

        self.assertIn("scripts/render_channel_config.py", initializer)


if __name__ == "__main__":
    unittest.main(verbosity=2)
