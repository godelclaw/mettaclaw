import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "channels"))

import effect_receipts  # noqa: E402
import context_sources  # noqa: E402
import mcp_bridge  # noqa: E402


class AtlasMcpIntegrationTests(unittest.TestCase):
    def test_real_stdio_query_records_exact_view_receipt(self):
        configured = os.environ.get("METTACLAW_ATLAS_TEST_ROOT", "").strip()
        if not configured:
            self.skipTest("METTACLAW_ATLAS_TEST_ROOT is not configured")
        atlas_root = pathlib.Path(configured).resolve()
        self.assertTrue((atlas_root / "atlas" / "mcp_server.py").is_file())

        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            garden = temporary / "garden"
            report = garden / "reports" / "demo" / "2026-08-27-result.md"
            report.parent.mkdir(parents=True)
            report.write_text(
                "# Result\n\nA revision-bearing Atlas integration witness.\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "-C", str(garden), "init"], check=True,
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            subprocess.run(
                ["git", "-C", str(garden), "config", "user.email",
                 "atlas@example.invalid"], check=True
            )
            subprocess.run(
                ["git", "-C", str(garden), "config", "user.name",
                 "Atlas Integration"], check=True
            )
            subprocess.run(["git", "-C", str(garden), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(garden), "commit", "-m", "fixture"],
                check=True, stdout=subprocess.DEVNULL
            )

            config = temporary / "mcp.json"
            receipts = temporary / "effects.jsonl"
            config.write_text(json.dumps({
                "mcpServers": {
                    "atlas-test": {
                        "type": "stdio",
                        "command": sys.executable,
                        "args": [
                            "-m", "atlas.mcp_server", "--root", str(garden)
                        ],
                        "cwd": str(atlas_root),
                    }
                }
            }), encoding="utf-8")
            with mock.patch.dict(os.environ, {
                "METTACLAW_MCP_CONFIG": str(config),
                "METTACLAW_EFFECT_RECEIPT_PATH": str(receipts),
                "METTACLAW_HISTORY_PATH": str(temporary / "history.metta"),
                "METTACLAW_TELEGRAM_LOG_PATH": str(temporary / "updates.jsonl"),
            }):
                returned = json.loads(mcp_bridge.call_tool(
                    "atlas-test",
                    "atlas_query",
                    json.dumps({
                        "text": "integration witness",
                        "worlds": ["reports:demo"],
                        "limit": 5,
                    }),
                ))
                rendered_receipts = effect_receipts.view()
                next_context = context_sources.bundle()

        self.assertFalse(returned.get("isError", returned.get("is_error", False)))
        self.assertIn("atlas-result-returned", rendered_receipts)
        self.assertIn("view:", rendered_receipts)
        self.assertIn("state:", rendered_receipts)
        self.assertIn("receipt:", rendered_receipts)
        self.assertTrue(next_context.startswith("CONTEXT_CERTIFICATE "))
        certificate = json.loads(next_context.splitlines()[0].partition(" ")[2])
        effect_source = next(
            source
            for source in certificate["sources"]
            if source["source_id"] == "effect-receipts"
        )
        self.assertEqual(effect_source["status"], "known")
        self.assertIn("atlas-result-returned", next_context)
        self.assertIn("view:", next_context)
        self.assertIn("state:", next_context)
        self.assertIn("receipt:", next_context)


if __name__ == "__main__":
    unittest.main(verbosity=2)
