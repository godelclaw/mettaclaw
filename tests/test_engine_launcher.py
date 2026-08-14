"""The shell launcher defaults and recovers independently of real engines."""

import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest


SOURCE_ROOT = pathlib.Path(__file__).resolve().parents[1]


class EngineLauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self.tmp.name)
        self.root = self.base / "agent"
        self.petta = self.base / "petta"
        self.pyenv = self.base / "python-env"
        self.root.mkdir()
        self.petta.mkdir()
        (self.pyenv / "bin").mkdir(parents=True)
        (self.root / "src").mkdir()
        shutil.copy2(SOURCE_ROOT / "run.sh", self.root / "run.sh")
        (self.root / "run.metta").write_text("", encoding="utf-8")
        (self.root / "src" / "memory_health.py").write_text(
            "", encoding="utf-8")
        self._script(self.pyenv / "bin" / "python3", "exit 0")
        self.result = self.base / "result"
        self._script(
            self.petta / "run.sh",
            'printf "petta:%s:%s\\n" "$METTACLAW_ACTIVE_ENGINE" "$*" '
            '>>"$ENGINE_TEST_RESULT"')
        self.cetta = self.base / "cetta"
        self._script(
            self.cetta,
            'printf "cetta:%s:%s\\n" "$METTACLAW_ACTIVE_ENGINE" "$*" '
            '>>"$ENGINE_TEST_RESULT"; '
            'if [ "${CETTA_REQUEST_RECYCLE:-0}" = 1 ]; then '
            'mkdir -p "$(dirname "$METTACLAW_RECYCLE_REQUEST_PATH")"; '
            ': >"$METTACLAW_RECYCLE_REQUEST_PATH"; fi; '
            'exit "${CETTA_EXIT_CODE:-0}"')
        self.env = os.environ.copy()
        for name in (
                "METTACLAW_ENGINE", "METTACLAW_ACTIVE_ENGINE",
                "METTACLAW_ENGINE_STATE_PATH",
                "METTACLAW_RECYCLE_REQUEST_PATH"):
            self.env.pop(name, None)
        self.env.update({
            "HOME": str(self.base / "home"),
            "XDG_STATE_HOME": str(self.base / "state"),
            "PETTA_ROOT": str(self.petta),
            "PETTA_PY_ENV": str(self.pyenv),
            "CETTA_BIN": str(self.cetta),
            "ENGINE_TEST_RESULT": str(self.result),
            "METTACLAW_SKIP_INITIALIZE": "1",
        })

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _script(path, body):
        path.write_text("#!/bin/sh\nset -eu\n" + body + "\n",
                        encoding="utf-8")
        path.chmod(0o755)

    @property
    def state_path(self):
        return self.base / "state" / "agent" / "engine"

    def select(self, name):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(name + "\n", encoding="utf-8")

    def launch(self, **extra_env):
        env = dict(self.env)
        env.update({key: str(value) for key, value in extra_env.items()})
        return subprocess.run(
            [str(self.root / "run.sh")], env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=10, check=False)

    def result_lines(self):
        return self.result.read_text(encoding="utf-8").splitlines()

    def test_absent_selection_uses_stable_petta_default(self):
        result = self.launch(CETTA_REQUEST_RECYCLE=1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.result_lines()), 1)
        self.assertTrue(self.result_lines()[0].startswith("petta:petta:"))

    def test_cetta_selection_launches_petta_profile(self):
        self.select("cetta")
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        line = self.result_lines()[0]
        self.assertTrue(line.startswith("cetta:cetta:"))
        self.assertIn("--lang petta", line)

    def test_clean_unrequested_cetta_stop_falls_back(self):
        self.select("cetta")
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([line.split(":", 1)[0]
                          for line in self.result_lines()],
                         ["cetta", "petta"])
        self.assertEqual(self.state_path.read_text(encoding="utf-8"),
                         "petta\n")
        self.assertIn("stopped without a recycle request", result.stderr)

    def test_cetta_failure_heals_selection_and_falls_back(self):
        self.select("cetta")
        result = self.launch(CETTA_EXIT_CODE=7)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([line.split(":", 1)[0]
                          for line in self.result_lines()],
                         ["cetta", "petta"])
        self.assertEqual(self.state_path.read_text(encoding="utf-8"),
                         "petta\n")
        self.assertIn("restoring stable engine 'petta'", result.stderr)

    def test_invalid_selection_uses_petta(self):
        self.select("not-an-engine")
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.result_lines()[0].startswith("petta:petta:"))
        self.assertIn("invalid persisted engine", result.stderr)

    def test_legacy_pleatta_selection_is_not_launched(self):
        self.select("pleatta")
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.result_lines()[0].startswith("petta:petta:"))
        self.assertEqual(self.state_path.read_text(encoding="utf-8"),
                         "petta\n")
        self.assertIn("PLeaTTa is temporarily disabled", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
