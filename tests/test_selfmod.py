import dataclasses
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ggb_bridge_ext  # noqa: E402
import selfmod  # noqa: E402


class SelfModTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        base = pathlib.Path(self.temporary.name)
        self.root = base / "protected"
        self.store = base / "proposals"
        (self.root / "src").mkdir(parents=True)
        self.target = self.root / "src" / "loop.metta"
        self.target.write_text("(= (f $x) $x)\n", encoding="utf-8")
        petta_root = pathlib.Path(
            os.environ.get("PETTA_ROOT", pathlib.Path.home() / "repos" / "PeTTa")
        )
        if not petta_root.is_dir():
            self.skipTest("PeTTa source tree is unavailable")
        self.settings = selfmod.Settings(
            root=self.root.resolve(),
            store=self.store,
            petta_root=petta_root.resolve(),
            parser_helper=ROOT / "scripts" / "metta_parse_only.pl",
            python_env=(pathlib.Path.home() / "miniforge3" / "envs" / "petta"),
            swipl=shutil.which("swipl") or "swipl",
            bwrap=shutil.which("bwrap") or "bwrap",
            timeout_seconds=8,
        )

    def propose_edit(self, new="(= (f $x) (g $x))\n"):
        prepared = selfmod.prepare_edit(
            "src/loop.metta",
            "(= (f $x) $x)\n",
            new,
            reason="unit test",
            actor="test-agent",
            settings=self.settings,
        )
        return selfmod.propose(
            prepared,
            settings=self.settings,
            policy=lambda _summary: "PASS",
        )

    def test_parser_accepts_complete_forms_without_evaluating_them(self):
        sentinel = pathlib.Path(self.temporary.name) / "must-not-exist"
        source = (
            "(= (f $x) $x)\n"
            "!(translatePredicate (open \"%s\" write $Out))\n" % sentinel
        )
        prepared = selfmod.prepare_write(
            "src/new.metta", source, settings=self.settings
        )
        manifest = selfmod.propose(
            prepared,
            settings=self.settings,
            policy=lambda _summary: "PASS",
        )
        self.assertEqual(manifest["syntax"]["status"], "pass")
        self.assertFalse(sentinel.exists())
        self.assertFalse((self.root / "src" / "new.metta").exists())

    def test_parser_rejects_unclosed_form_and_stores_nothing(self):
        prepared = selfmod.prepare_write(
            "src/broken.metta", "(= (f $x) $x\n", settings=self.settings
        )
        with self.assertRaisesRegex(selfmod.SelfModError, "parser rejected"):
            selfmod.propose(
                prepared,
                settings=self.settings,
                policy=lambda _summary: "PASS",
            )
        self.assertFalse(self.store.exists())

    def test_exact_candidate_is_hashed_and_target_remains_unchanged(self):
        manifest = self.propose_edit()
        proposal_dir = self.store / manifest["proposal_id"]
        candidate = (proposal_dir / "candidate").read_bytes()
        self.assertEqual(
            hashlib.sha256(candidate).hexdigest(), manifest["candidate_sha256"]
        )
        self.assertEqual(candidate, b"(= (f $x) (g $x))\n")
        self.assertEqual(self.target.read_text(), "(= (f $x) $x)\n")
        self.assertEqual(manifest["provenance"]["actor"], "test-agent")
        self.assertEqual(manifest["state"], "ready")

    def test_policy_receives_structured_digest_not_candidate_text(self):
        seen = []
        prepared = selfmod.prepare_write(
            "src/new.py", "private candidate", settings=self.settings
        )
        selfmod.propose(
            prepared,
            settings=self.settings,
            policy=lambda summary: seen.append(summary) or "PASS",
        )
        self.assertEqual(seen[0]["target"], "src/new.py")
        self.assertEqual(seen[0]["candidate_size"], len("private candidate"))
        self.assertNotIn("private candidate", json.dumps(seen[0]))

    def test_traversal_and_symlink_components_are_rejected(self):
        with self.assertRaisesRegex(selfmod.SelfModError, "may not contain"):
            selfmod.prepare_write("../escape.metta", "()", settings=self.settings)
        outside = pathlib.Path(self.temporary.name) / "outside"
        outside.mkdir()
        (self.root / "linked").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(selfmod.SelfModError, "symlink"):
            selfmod.prepare_write("linked/escape.metta", "()", settings=self.settings)
        leaf = self.root / "src" / "leaf.metta"
        leaf.symlink_to(self.target)
        with self.assertRaisesRegex(selfmod.SelfModError, "symlink"):
            selfmod.prepare_write("src/leaf.metta", "()", settings=self.settings)

    def test_proposal_store_cannot_live_inside_protected_root(self):
        inside = dataclasses.replace(
            self.settings, store=self.root / ".proposals"
        )
        prepared = selfmod.prepare_write(
            "src/new.metta", "(= (new) ok)\n", settings=inside
        )
        with self.assertRaisesRegex(selfmod.SelfModError, "outside"):
            selfmod.propose(prepared, settings=inside)

    def test_supervisor_verifies_then_atomically_promotes(self):
        manifest = self.propose_edit()
        command = [
            sys.executable,
            str(ROOT / "scripts" / "selfmod_supervisor.py"),
            "promote",
            manifest["proposal_id"],
            "--root",
            str(self.root),
            "--store",
            str(self.store),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["state"], "promoted")
        self.assertEqual(self.target.read_text(), "(= (f $x) (g $x))\n")
        self.assertTrue(
            (self.store / manifest["proposal_id"] / "promotion.json").is_file()
        )
        leftovers = list((self.root / "src").glob(".selfmod-*.tmp"))
        self.assertEqual(leftovers, [])

    def test_supervisor_rejects_tampered_candidate(self):
        manifest = self.propose_edit()
        proposal_dir = self.store / manifest["proposal_id"]
        (proposal_dir / "candidate").write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(selfmod.SelfModError, "digest mismatch"):
            selfmod.verify_proposal(manifest["proposal_id"], settings=self.settings)
        self.assertEqual(self.target.read_text(), "(= (f $x) $x)\n")

    def test_supervisor_rejects_manifest_retargeting(self):
        manifest = self.propose_edit()
        proposal_dir = self.store / manifest["proposal_id"]
        manifest_path = proposal_dir / "manifest.json"
        changed = json.loads(manifest_path.read_text(encoding="utf-8"))
        changed["target"] = "src/other.metta"
        manifest_path.write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaisesRegex(selfmod.SelfModError, "manifest digest"):
            selfmod.verify_proposal(manifest["proposal_id"], settings=self.settings)

    def test_supervisor_rejects_stale_base(self):
        manifest = self.propose_edit()
        self.target.write_text("(= (f $x) changed)\n", encoding="utf-8")
        with self.assertRaisesRegex(selfmod.SelfModError, "stale"):
            selfmod.verify_proposal(manifest["proposal_id"], settings=self.settings)
        self.assertEqual(self.target.read_text(), "(= (f $x) changed)\n")

    def test_semantic_check_contains_side_effects_in_private_tmp(self):
        if not shutil.which("bwrap"):
            self.skipTest("bubblewrap unavailable")
        host_sentinel = pathlib.Path("/tmp") / (
            "pettaclaw-semantic-" + pathlib.Path(self.temporary.name).name
        )
        host_sentinel.unlink(missing_ok=True)
        self.addCleanup(host_sentinel.unlink, missing_ok=True)
        candidate = pathlib.Path(self.temporary.name) / "semantic.metta"
        candidate.write_text(
            "!(translatePredicate (open \"%s\" write $Out))\n" % host_sentinel,
            encoding="utf-8",
        )
        receipt = selfmod.check_semantics(candidate, self.settings)
        self.assertEqual(receipt["status"], "pass")
        self.assertFalse(host_sentinel.exists())

    def test_ggb_wrapper_returns_proposal_receipt(self):
        env = {
            "METTACLAW_PROTECTED_ROOT": str(self.root),
            "METTACLAW_SELFMOD_PROPOSAL_STORE": str(self.store),
            "PETTA_ROOT": str(self.settings.petta_root),
            "METTACLAW_METTA_PARSE_HELPER": str(self.settings.parser_helper),
        }
        with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(
            ggb_bridge_ext, "ggbSafeSelfMod", return_value="PASS"
        ):
            result = ggb_bridge_ext.ggbProposeEdit(
                "src/loop.metta",
                "(= (f $x) $x)\n",
                "(= (f $x) (wrapped $x))\n",
                "wrapper test",
            )
        self.assertIn("PROPOSAL_READY", result)
        self.assertIn("promotion=pending", result)
        self.assertEqual(self.target.read_text(), "(= (f $x) $x)\n")

    def test_optional_governance_fails_closed_when_requested(self):
        env = {
            "METTACLAW_PROTECTED_ROOT": str(self.root),
            "METTACLAW_SELFMOD_PROPOSAL_STORE": str(self.store),
            "PETTA_ROOT": str(self.settings.petta_root),
            "METTACLAW_METTA_PARSE_HELPER": str(self.settings.parser_helper),
            "METTACLAW_SELFMOD_REQUIRE_GOVERNANCE": "1",
        }
        with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(
            ggb_bridge_ext, "ggbSafeSelfMod", return_value="BLOCK"
        ):
            result = ggb_bridge_ext.ggbProposeWrite(
                "src/new.metta", "(= (new) ok)\n"
            )
        self.assertIn("PROPOSAL_BLOCKED", result)
        self.assertFalse(self.store.exists())


if __name__ == "__main__":
    unittest.main()
