import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import runtime_watch  # noqa: E402


class RuntimeWatchTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = pathlib.Path(self.temporary.name)
        self.args = mock.Mock(
            root=root, service="agent.service", health=root / "health.json",
            working_set=root / "working.json",
            canonical_memory=root / "memory.jsonl", chroma=root / "chroma",
            deployment=root / "deployment.json", log=root / "watch.jsonl",
            failures=3,
        )
        self.args.canonical_memory.write_bytes(b"preserved")
        self.deployment = {
            "status": "probation", "candidate": "candidate",
            "previous": "previous", "baseline_canonical_bytes": 9,
            "baseline_memories": 100, "probation_until": 2000,
        }

    def test_legitimate_rest_is_healthy(self):
        facts = {"state": "ok", "problems": [], "memories": 100}
        with mock.patch.object(runtime_watch.runtime_health, "status",
                               return_value=facts), \
             mock.patch.object(runtime_watch, "_service_active",
                               return_value=True), \
             mock.patch.object(runtime_watch, "_head",
                               return_value="candidate"):
            value = runtime_watch.observe(self.args, self.deployment, now=1000)
        self.assertEqual(value["problems"], [])

    def test_memory_regression_is_a_failure(self):
        facts = {"state": "ok", "problems": [], "memories": 99}
        with mock.patch.object(runtime_watch.runtime_health, "status",
                               return_value=facts), \
             mock.patch.object(runtime_watch, "_service_active",
                               return_value=True), \
             mock.patch.object(runtime_watch, "_head",
                               return_value="candidate"):
            value = runtime_watch.observe(self.args, self.deployment, now=1000)
        self.assertIn("memory-count-regressed", value["problems"])

    def test_third_probation_failure_invokes_rollback(self):
        state = dict(self.deployment, consecutive_failures=2)
        self.args.deployment.write_text(json.dumps(state), encoding="utf-8")
        observation = {"problems": ["telegram-poll-stale"], "active": True,
                       "head": "candidate", "runtime": {},
                       "observed_at": 1000, "canonical_memory_bytes": 9}
        with mock.patch.object(runtime_watch, "observe",
                               return_value=observation), \
             mock.patch.object(runtime_watch, "_rollback",
                               return_value=(True, "rolled-back")) as rollback:
            code = runtime_watch.manage(self.args, now=1000)
        self.assertEqual(code, 1)
        rollback.assert_called_once()
        saved = json.loads(self.args.deployment.read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "rolled_back")


if __name__ == "__main__":
    unittest.main(verbosity=2)
