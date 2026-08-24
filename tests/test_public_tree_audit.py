#!/usr/bin/env python3
import os
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
AUDIT = ROOT / "scripts" / "audit_public_tree.py"


def run(*args, cwd, check=True):
    return subprocess.run(
        args, cwd=cwd, check=check, capture_output=True, text=True)


class PublicTreeAuditTest(unittest.TestCase):
    def make_repo(self):
        tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(tmp.name)
        run("git", "init", "-q", cwd=root)
        run("git", "config", "user.name", "Audit Test", cwd=root)
        run("git", "config", "user.email", "audit@example.invalid", cwd=root)
        (root / "config").mkdir()
        (root / ".gitignore").write_text(
            "config/secrets.env\nmemory/\n", encoding="utf-8")
        (root / "public.py").write_text("print('public')\n", encoding="utf-8")
        (root / "config" / "secrets.env").write_text(
            "METTACLAW_TELEGRAM_OPERATOR_IDS='777000777'\n",
            encoding="utf-8")
        os.chmod(root / "config" / "secrets.env", 0o600)
        run("git", "add", ".gitignore", "public.py", cwd=root)
        run("git", "commit", "-qm", "initial", cwd=root)
        return tmp, root

    def test_clean_public_tree_passes(self):
        tmp, root = self.make_repo()
        self.addCleanup(tmp.cleanup)
        result = run("python3", str(AUDIT), "--history", "--repo", str(root),
                     cwd=root, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_secret_match_is_reported_without_printing_value(self):
        tmp, root = self.make_repo()
        self.addCleanup(tmp.cleanup)
        (root / "leak.txt").write_text("operator=777000777\n", encoding="utf-8")
        run("git", "add", "leak.txt", cwd=root)
        run("git", "commit", "-qm", "bad", cwd=root)
        result = run("python3", str(AUDIT), "--history", "--repo", str(root),
                     cwd=root, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("leak.txt", result.stderr)
        self.assertNotIn("777000777", result.stderr)

    def test_unpublished_local_ref_does_not_taint_head(self):
        tmp, root = self.make_repo()
        self.addCleanup(tmp.cleanup)
        run("git", "switch", "-qc", "private-experiment", cwd=root)
        (root / "private.txt").write_text(
            "operator=777000777\n", encoding="utf-8")
        run("git", "add", "private.txt", cwd=root)
        run("git", "commit", "-qm", "private experiment", cwd=root)
        run("git", "switch", "-q", "master", cwd=root)
        result = run(
            "python3", str(AUDIT), "--history", "--revision", "HEAD",
            "--repo", str(root), cwd=root, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_private_runtime_path_is_rejected(self):
        tmp, root = self.make_repo()
        self.addCleanup(tmp.cleanup)
        (root / "memory").mkdir()
        (root / "memory" / "history.metta").write_text("private\n", encoding="utf-8")
        run("git", "add", "-f", "memory/history.metta", cwd=root)
        result = run("python3", str(AUDIT), "--repo", str(root),
                     cwd=root, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("memory/history.metta", result.stderr)

    def test_no_unconsented_process_jail_in_tracked_runtime(self):
        forbidden = ("b" + "wrap", "bubble" + "wrap")
        tracked = run("git", "ls-files", "-z", cwd=ROOT).stdout.split("\0")
        found = []
        for relative in tracked:
            if not relative:
                continue
            path = ROOT / relative
            try:
                text = path.read_text(encoding="utf-8").lower()
            except (OSError, UnicodeDecodeError):
                continue
            if any(token in text for token in forbidden):
                found.append(relative)
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
