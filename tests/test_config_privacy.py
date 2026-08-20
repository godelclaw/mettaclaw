#!/usr/bin/env python3
import os
import pathlib
import subprocess
import tempfile
import textwrap
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class ConfigPrivacyTest(unittest.TestCase):
    def test_default_transport_state_is_outside_checkout(self):
        environment = os.environ.copy()
        environment["XDG_STATE_HOME"] = "/tmp/pettaclaw-state"
        environment["METTACLAW_INSTANCE"] = "test-claw"
        result = subprocess.run(
            ["python3", str(ROOT / "scripts" / "config_to_env.py"),
             str(ROOT / "config" / "default.toml"), str(ROOT)],
            check=True, capture_output=True, text=True, env=environment)

        self.assertIn(
            "METTACLAW_TELEGRAM_OFFSET_PATH='/tmp/pettaclaw-state/test-claw/telegram/offset'",
            result.stdout)
        self.assertIn(
            "METTACLAW_TELEGRAM_LOG_PATH='/tmp/pettaclaw-state/test-claw/telegram/updates.jsonl'",
            result.stdout)
        self.assertIn("CETTA_ROOT='", result.stdout)
        self.assertIn("/repos/CeTTa'", result.stdout)
        self.assertIn("METTACLAW_RECENT_ACTION_TURNS='12'", result.stdout)
        self.assertIn("METTACLAW_CONVERSATION_EVENTS='64'", result.stdout)
        self.assertNotIn(str(ROOT / "telegram_offset.txt"), result.stdout)
        self.assertNotIn(str(ROOT / "telegram_updates.jsonl"), result.stdout)

    def test_identity_bearing_telegram_values_are_not_generated(self):
        config = textwrap.dedent("""
            [paths]
            petta_root = "/tmp/petta"

            [channel]
            kind = "telegram"

            [telegram]
            allow_private = true
            operator_ids = ["700001"]
            light_arm_ids = ["700002"]
            sender_names = ["700001:Operator"]
            allowed_chat_ids = ["-700003"]
        """)
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "local.toml"
            path.write_text(config, encoding="utf-8")
            result = subprocess.run(
                ["python3", str(ROOT / "scripts" / "config_to_env.py"),
                 str(path), str(ROOT)],
                check=True, capture_output=True, text=True)

        self.assertIn("METTACLAW_TELEGRAM_ALLOW_PRIVATE", result.stdout)
        self.assertNotIn("700001", result.stdout)
        self.assertNotIn("700002", result.stdout)
        self.assertNotIn("700003", result.stdout)
        self.assertNotIn("METTACLAW_TELEGRAM_OPERATOR_IDS", result.stdout)
        self.assertNotIn("METTACLAW_TELEGRAM_LIGHT_ARM_IDS", result.stdout)
        self.assertNotIn("METTACLAW_TELEGRAM_SENDER_NAMES", result.stdout)
        self.assertNotIn("METTACLAW_TELEGRAM_ALLOWED_CHAT_IDS", result.stdout)


if __name__ == "__main__":
    unittest.main()
