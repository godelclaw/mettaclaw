import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import mcp_bridge  # noqa: E402


class McpBridgeAtlasTests(unittest.TestCase):
    def test_structured_content_precedes_text_projection(self):
        structured = {
            "view_id": "view:structured",
            "state_revision": "state:one",
            "receipt": {"receipt_id": "receipt:one"},
        }
        result = {
            "structuredContent": structured,
            "content": [{"type": "text", "text": "not json"}],
            "isError": False,
        }
        self.assertEqual(mcp_bridge._atlas_payload(result), structured)

    def test_text_fallback_and_error_rejection(self):
        payload = {
            "revision_id": "state:two",
            "receipt": {"receipt_id": "receipt:two"},
        }
        result = {
            "content": [
                {"type": "text", "text": __import__("json").dumps(payload)}
            ],
            "isError": False,
        }
        self.assertEqual(mcp_bridge._atlas_payload(result), payload)
        self.assertIsNone(
            mcp_bridge._atlas_payload(
                {"structuredContent": payload, "isError": True}
            )
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
