import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class IterAuthoringEngineTests(unittest.TestCase):
    def run_probe(self, engine, directory):
        env = dict(os.environ)
        env.update({
            "METTACLAW_ENGINE": engine,
            "METTACLAW_ITER_PROCESS_DIR": str(directory),
            "METTACLAW_SKIP_INITIALIZE": "1",
        })
        command = ["./run.sh", "tests/iter_authoring_probe.metta"]
        if engine == "cetta":
            cetta = Path(env.get(
                "CETTA_BIN", Path.home() / "repos" / "CeTTa-runtime" / "cetta"
            ))
            if not cetta.is_file():
                self.skipTest("CeTTa executable is unavailable")
            env["CETTA_BIN"] = str(cetta)
            petta_root = Path(env.get(
                "PETTA_ROOT", Path.home() / "repos" / "PeTTa"
            ))
            env["PYTHONPATH"] = os.pathsep.join((
                str(ROOT / "src"), str(ROOT / "channels"),
                str(ROOT / "repos" / "petta_lib_chromadb"),
            ))
            # Non-live run.sh intentionally launches only the requested file.
            # The real CeTTa service uses an explicit manifest, so this probe
            # mirrors the relevant manifest entries instead of testing an
            # unrealistically sparse one-file invocation.
            command = [
                str(cetta), "--lang", "petta", "--import-mode", "ancestor-walk",
                str(ROOT / "cetta_bootstrap.metta"),
                str(petta_root / "lib" / "lib_import.metta"),
                str(ROOT / "src" / "iter_process_policy.metta"),
                str(ROOT / "src" / "skills.metta"),
                str(ROOT / "tests" / "iter_authoring_probe.metta"),
            ]
        return subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=40,
        )

    def test_direct_authoring_crosses_petta_and_cetta_boundaries(self):
        source = (
            "def transform(messages, tools):\n"
            "    return messages + [2], tools\n"
        )
        for engine in ("petta", "cetta"):
            with self.subTest(engine=engine), tempfile.TemporaryDirectory() as raw:
                directory = Path(raw) / "transformations"
                result = self.run_probe(engine, directory)
                self.assertEqual(result.returncode, 0, result.stderr[-3000:])
                self.assertIn("ITER_AUTHORING_OK", result.stdout)
                self.assertIn('"state":"installed"', result.stdout)
                self.assertIn('"state":"disabled"', result.stdout)
                self.assertIn('"state":"enabled"', result.stdout)
                self.assertEqual(
                    (directory / "10_probe.py").read_text(encoding="utf-8"),
                    source,
                )
                self.assertFalse((directory / "_10_probe.py").exists())


if __name__ == "__main__":
    unittest.main()
