import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import iter_process_adapter as adapter  # noqa: E402


class IterProcessAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, name, source):
        (self.directory / name).write_text(source, encoding="utf-8")

    def test_capture_is_sorted_and_ignores_private_files(self):
        self.write("20_second.py", "def transform(messages, tools): return messages, tools")
        self.write("10_first.py", "def transform(messages, tools): return messages, tools")
        self.write("_ignored.py", "raise RuntimeError('must not load')")
        snapshot = adapter.capture(self.directory)
        self.assertEqual(
            [process.name for process in snapshot.processes],
            ["10_first.py", "20_second.py"],
        )

    def test_empty_directory_is_identity(self):
        snapshot, result = adapter.run_directory(
            self.directory, ["message"], ["tool"]
        )
        self.assertEqual(snapshot.processes, ())
        self.assertEqual((result.messages, result.tools),
                         (["message"], ["tool"]))

    def test_order_is_semantic(self):
        self.write(
            "10_append.py",
            "def transform(messages, tools):\n"
            "    return messages + ['a'], tools\n",
        )
        self.write(
            "20_double.py",
            "def transform(messages, tools):\n"
            "    return messages + messages, tools\n",
        )
        _, result = adapter.run_directory(self.directory, [], [])
        self.assertEqual(result.messages, ["a", "a"])

    def test_failure_stutters_and_later_process_runs(self):
        self.write(
            "10_append.py",
            "def transform(messages, tools): return messages + ['a'], tools\n",
        )
        self.write(
            "20_fail.py",
            "def transform(messages, tools): raise RuntimeError('broken')\n",
        )
        self.write(
            "30_append.py",
            "def transform(messages, tools): return messages + ['b'], tools\n",
        )
        _, result = adapter.run_directory(self.directory, [], [])
        self.assertEqual(result.messages, ["a", "b"])
        self.assertEqual(
            [item.status for item in result.observations],
            ["success", "failure", "success"],
        )
        self.assertIn("RuntimeError: broken", result.observations[1].detail)

    def test_started_turn_uses_captured_bytes_and_next_turn_refreshes(self):
        self.write(
            "10_value.py",
            "def transform(messages, tools): return messages + ['old'], tools\n",
        )
        current = adapter.capture(self.directory)
        self.write(
            "10_value.py",
            "def transform(messages, tools): return messages + ['new'], tools\n",
        )
        next_snapshot = adapter.capture(self.directory)
        self.assertNotEqual(current.revision, next_snapshot.revision)
        self.assertEqual(adapter.run(current, [], []).messages, ["old"])
        self.assertEqual(adapter.run(next_snapshot, [], []).messages, ["new"])

    def test_timeout_is_failure(self):
        self.write(
            "10_timeout.py",
            "import time\n"
            "def transform(messages, tools):\n"
            "    time.sleep(2)\n"
            "    return messages, tools\n",
        )
        with mock.patch.dict(
            os.environ, {"METTACLAW_ITER_PROCESS_TIMEOUT_SECONDS": "0.05"}
        ):
            _, result = adapter.run_directory(self.directory, ["before"], [])
        self.assertEqual(result.messages, ["before"])
        self.assertEqual(result.observations[0].status, "failure")
        self.assertEqual(result.observations[0].detail, "TIMEOUT")

    def test_malformed_result_is_failure(self):
        self.write(
            "10_bad.py",
            "def transform(messages, tools): return messages\n",
        )
        _, result = adapter.run_directory(self.directory, ["before"], [])
        self.assertEqual((result.messages, result.tools), (["before"], []))
        self.assertIn("must return", result.observations[0].detail)

    def test_json_bridge_reports_revision_and_observations(self):
        self.write(
            "10_append.py",
            "def transform(messages, tools): return messages + ['x'], tools\n",
        )
        output = json.loads(
            adapter.run_json(self.directory, '["before"]', "[]")
        )
        self.assertEqual(output["messages"], ["before", "x"])
        self.assertEqual(output["observations"][0]["status"], "success")
        self.assertEqual(len(output["revision"]), 64)

    def test_disabled_request_is_identity_without_directory_capture(self):
        with mock.patch.object(adapter, "capture") as capture:
            output = json.loads(adapter.prepare_request_json(
                "system", "activity", "skills", 0
            ))
        capture.assert_not_called()
        self.assertEqual(
            output["messages"],
            [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "activity"},
            ],
        )
        self.assertFalse(output["transformations_enabled"])
        self.assertEqual(output["observations"], [])

    def test_enabled_request_uses_exact_transformed_order_and_advertisement(self):
        self.write(
            "10_transform.py",
            "def transform(messages, tools):\n"
            "    return [messages[1], messages[0], "
            "{'role': 'user', 'content': 'added'}], []\n",
        )
        with mock.patch.dict(os.environ, {
            "METTACLAW_ITER_PROCESS_DIR": str(self.directory)
        }):
            encoded = adapter.prepare_request_json(
                "system", "activity", "skills", 1
            )
        output = json.loads(encoded)
        self.assertEqual(
            [message["content"] for message in output["messages"]],
            ["activity", "system", "added"],
        )
        self.assertEqual(output["tools"], [])
        self.assertEqual(
            output["authority"],
            {
                "executable": ["command-batch"],
                "permitted": ["command-batch"],
            },
        )
        rendered = adapter.render_request_json(encoded)
        self.assertLess(rendered.index("USER: activity"),
                        rendered.index("SYSTEM: system"))
        self.assertIn("USER: added", rendered)

    def test_request_failure_stutters_and_is_rendered_as_evidence(self):
        self.write(
            "10_broken.py",
            "def transform(messages, tools): raise RuntimeError('broken')\n",
        )
        with mock.patch.dict(os.environ, {
            "METTACLAW_ITER_PROCESS_DIR": str(self.directory)
        }):
            encoded = adapter.prepare_request_json(
                "system", "activity", "skills", True
            )
        output = json.loads(encoded)
        self.assertEqual(output["messages"][0]["content"], "system")
        self.assertEqual(output["observations"][0]["status"], "failure")
        observations = adapter.render_observations_json(encoded)
        self.assertIn("10_broken.py:failure", observations)
        self.assertIn("RuntimeError: broken", observations)


if __name__ == "__main__":
    unittest.main()
