import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "src"))
import iter_authoring as authoring  # noqa: E402
import iter_process_adapter as adapter  # noqa: E402
import ggb_bridge_ext  # noqa: E402


class IterAuthoringTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name) / "transformations"
        self.environment = mock.patch.dict(os.environ, {
            "METTACLAW_ITER_PROCESS_DIR": str(self.directory),
            "METTACLAW_SELFMOD_PROPOSAL_STORE": str(
                Path(self.temporary.name) / "proposals"
            ),
        })
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    @staticmethod
    def decode(receipt):
        return json.loads(receipt)

    @staticmethod
    def source(value):
        return (
            "def transform(messages, tools):\n"
            "    return messages + [%r], tools\n" % value
        )

    def test_write_is_exact_and_activates_only_at_next_capture(self):
        current = adapter.capture(self.directory)
        source = self.source("next")

        receipt = self.decode(
            authoring.write_transformation("10_value.py", source)
        )
        next_snapshot = adapter.capture(self.directory)

        self.assertEqual(receipt["state"], "installed")
        self.assertEqual(receipt["syntax"], "pass")
        self.assertEqual(receipt["before_revision"], current.revision)
        self.assertEqual(receipt["activation_revision"], next_snapshot.revision)
        self.assertEqual(
            receipt["sha256"], hashlib.sha256(source.encode()).hexdigest()
        )
        self.assertNotEqual(current.revision, next_snapshot.revision)
        self.assertEqual(adapter.run(current, [], []).messages, [])
        self.assertEqual(
            adapter.run(next_snapshot, [], []).messages, ["next"]
        )

    def test_replace_receipt_binds_prior_and_new_bytes(self):
        old = self.source("old")
        new = self.source("new")
        authoring.write_transformation("10_value.py", old)

        receipt = self.decode(
            authoring.write_transformation("10_value.py", new)
        )

        self.assertEqual(
            receipt["prior_sha256"], hashlib.sha256(old.encode()).hexdigest()
        )
        self.assertEqual(
            receipt["sha256"], hashlib.sha256(new.encode()).hexdigest()
        )
        self.assertEqual(
            (self.directory / "10_value.py").read_text(encoding="utf-8"), new
        )

    def test_syntax_failure_is_installed_then_stutters(self):
        receipt = self.decode(
            authoring.write_transformation("10_broken.py", "def transform(:\n")
        )
        snapshot, result = adapter.run_directory(
            self.directory, ["before"], ["tool"]
        )

        self.assertEqual(receipt["state"], "installed")
        self.assertEqual(receipt["syntax"], "fail")
        self.assertEqual(receipt["activation_revision"], snapshot.revision)
        self.assertEqual((result.messages, result.tools), (["before"], ["tool"]))
        self.assertEqual(result.observations[0].status, "failure")
        self.assertIn("SyntaxError", result.observations[0].detail)

    def test_disable_and_enable_are_reversible_next_capture_changes(self):
        source = self.source("active")
        authoring.write_transformation("10_value.py", source)
        active_revision = adapter.capture(self.directory).revision

        disabled = self.decode(
            authoring.disable_transformation("10_value.py")
        )
        disabled_snapshot = adapter.capture(self.directory)
        enabled = self.decode(authoring.enable_transformation("10_value.py"))
        enabled_snapshot = adapter.capture(self.directory)

        self.assertEqual(disabled["state"], "disabled")
        self.assertEqual(disabled_snapshot.processes, ())
        self.assertNotEqual(active_revision, disabled_snapshot.revision)
        self.assertEqual(enabled["state"], "enabled")
        self.assertEqual(enabled_snapshot.revision, active_revision)
        self.assertEqual(
            adapter.run(enabled_snapshot, [], []).messages, ["active"]
        )

    def test_list_reports_active_disabled_and_revision(self):
        authoring.write_transformation("10_active.py", self.source("active"))
        authoring.write_transformation("20_disabled.py", self.source("off"))
        authoring.disable_transformation("20_disabled.py")

        observed = self.decode(authoring.list_transformations())

        self.assertEqual(observed["state"], "observed")
        self.assertEqual(
            [item["name"] for item in observed["active"]], ["10_active.py"]
        )
        self.assertEqual(
            [item["name"] for item in observed["disabled"]],
            ["_20_disabled.py"],
        )
        self.assertEqual(observed["revision"], adapter.capture(
            self.directory
        ).revision)

    def test_name_scope_is_exact_but_shell_remains_a_separate_authority(self):
        for name in ("../escape.py", "/tmp/escape.py", "_hidden.py", "plain"):
            with self.subTest(name=name):
                receipt = self.decode(
                    authoring.write_transformation(name, self.source("x"))
                )
                self.assertEqual(receipt["state"], "error")
        self.assertFalse((Path(self.temporary.name) / "escape.py").exists())

    def test_direct_authoring_does_not_create_a_promotion_proposal(self):
        receipt = self.decode(
            authoring.write_transformation("10_direct.py", self.source("x"))
        )
        proposal_store = Path(os.environ["METTACLAW_SELFMOD_PROPOSAL_STORE"])

        self.assertEqual(receipt["state"], "installed")
        self.assertFalse(proposal_store.exists())
        self.assertNotIn("promotion", receipt)

    def test_post_rename_sync_failure_cannot_hide_the_installed_effect(self):
        source = self.source("durability-unconfirmed")
        with mock.patch.object(
            authoring, "_sync_directory",
            return_value=("unconfirmed", "OSError: unsupported"),
        ):
            receipt = self.decode(
                authoring.write_transformation("10_value.py", source)
            )

        self.assertEqual(receipt["state"], "installed")
        self.assertEqual(receipt["directory_sync"], "unconfirmed")
        self.assertEqual(
            (self.directory / "10_value.py").read_text(encoding="utf-8"),
            source,
        )
        self.assertEqual(
            adapter.run(adapter.capture(self.directory), [], []).messages,
            ["durability-unconfirmed"],
        )

    def test_proposal_only_surface_cannot_activate_but_direct_authoring_can(self):
        """Witness the exact hosted gap that upstream Iter does not impose."""

        root = Path(self.temporary.name) / "protected"
        self.directory = root / "memory" / "transformations"
        self.directory.mkdir(parents=True)
        proposals = Path(self.temporary.name) / "pending-proposals"
        source = self.source("activated")
        environment = {
            "METTACLAW_PROTECTED_ROOT": str(root),
            "METTACLAW_ITER_PROCESS_DIR": str(self.directory),
            "METTACLAW_SELFMOD_PROPOSAL_STORE": str(proposals),
            "METTACLAW_SELFMOD_REQUIRE_GOVERNANCE": "0",
            "METTACLAW_SELFMOD_SEMANTIC_CHECK": "0",
        }
        with mock.patch.dict(os.environ, environment, clear=False):
            proposed = ggb_bridge_ext.ggbProposeWrite(
                "memory/transformations/10_value.py", source, "gap witness"
            )
            after_proposal = adapter.capture(self.directory)
            target_absent_after_proposal = not (
                self.directory / "10_value.py"
            ).exists()

            repaired = self.decode(
                authoring.write_transformation("10_value.py", source)
            )
            after_direct_write = adapter.capture(self.directory)

        self.assertIn("PROPOSAL_READY", proposed)
        self.assertIn("promotion=pending", proposed)
        self.assertEqual(after_proposal.processes, ())
        self.assertTrue(target_absent_after_proposal)
        self.assertEqual(repaired["state"], "installed")
        self.assertEqual(
            adapter.run(after_direct_write, [], []).messages, ["activated"]
        )


if __name__ == "__main__":
    unittest.main()
