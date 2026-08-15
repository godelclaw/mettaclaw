"""The real PeTTa boundary must not eagerly execute a command argument."""

import json
import os
import pathlib
import shlex
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class CommandDispatchEngineTest(unittest.TestCase):
    def _petta_root(self):
        return pathlib.Path(os.environ.get(
            "PETTA_ROOT", pathlib.Path.home() / "repos" / "PeTTa"))

    def _cetta_binary(self):
        return pathlib.Path(os.environ.get(
            "CETTA_BIN", pathlib.Path.home() / "repos" / "CeTTa" / "cetta"))

    def _cetta_env(self):
        env = dict(os.environ)
        python_env = pathlib.Path(os.environ.get(
            "PETTA_PY_ENV",
            pathlib.Path.home() / "miniforge3" / "envs" / "petta"))
        env["PYTHONPATH"] = os.pathsep.join((
            os.fspath(ROOT / "src"), os.fspath(ROOT / "channels"),
            os.fspath(ROOT / "repos" / "petta_lib_chromadb"),
        ))
        if python_env.is_dir():
            env["PATH"] = os.pathsep.join((
                os.fspath(python_env / "bin"), env.get("PATH", ""),
            ))
            env["LD_LIBRARY_PATH"] = os.pathsep.join((
                os.fspath(python_env / "lib"),
                env.get("LD_LIBRARY_PATH", ""),
            ))
            env["PYTHONHOME"] = os.fspath(python_env)
            env["PYTHONNOUSERSITE"] = "1"
        return env

    def test_petta_executes_quoted_batch_once(self):
        petta = self._petta_root()
        if not (petta / "run.sh").is_file():
            self.skipTest("PeTTa checkout is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            directory = pathlib.Path(directory)
            effect = directory / "effect.log"
            probe = directory / "probe.metta"
            command = "printf 'effect-once\\n' >> %s" % shlex.quote(
                os.fspath(effect))
            response = "((shell %s))" % json.dumps(command)
            probe.write_text(
                "!(import! &self (library lib_import))\n"
                "!(import! &self ./src/skills)\n"
                "!(println! (run-command-batch-once 424242 "
                "(quote %s)))\n" % response,
                encoding="utf-8",
            )
            env = dict(os.environ)
            env.update({
                "METTACLAW_SKIP_INITIALIZE": "1",
                "METTACLAW_ENGINE": "petta",
                "METTACLAW_ENGINE_STATE_PATH": os.fspath(
                    directory / "engine-selection"),
            })
            result = subprocess.run(
                ["./run.sh", os.fspath(probe)], cwd=ROOT, env=env,
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            self.assertEqual(effect.read_text(encoding="utf-8"),
                             "effect-once\n")

    def test_petta_runs_timed_continuation_once(self):
        petta = self._petta_root()
        if not (petta / "run.sh").is_file():
            self.skipTest("PeTTa checkout is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            directory = pathlib.Path(directory)
            effect = directory / "continued.log"
            probe = directory / "continuation.metta"
            command = "printf 'continued-once\\n' >> %s" % shlex.quote(
                os.fspath(effect))
            probe.write_text(
                "!(import! &self (library lib_import))\n"
                "!(import! &self ./lib_mettaclaw)\n"
                "!(let* (($p (coordinate iteration 7 "
                "(coordinate loops 0 (coordinate sleep-interval 1 "
                "(coordinate last-results before "
                "(coordinate last-heartbeat 9 "
                "(coordinate active-policy agent "
                "(coordinate autonomous-ready 0 "
                "(coordinate pending-continuation "
                "(continuation-value (shell %s)) "
                "coordinates-empty))))))))) "
                "($resumed (applyTimedContinuation $p 1)) "
                "($_ (assert (== (loop-budget $resumed) 2))) "
                "($_ (assert (== (loop-pending-continuation $resumed) "
                "no-continuation)))) (println! REST_CONTINUATION_OK))\n"
                % json.dumps(command),
                encoding="utf-8",
            )
            env = dict(os.environ)
            env.update({
                "METTACLAW_SKIP_INITIALIZE": "1",
                "METTACLAW_ENGINE": "petta",
                "METTACLAW_ENGINE_STATE_PATH": os.fspath(
                    directory / "engine-selection"),
            })
            result = subprocess.run(
                ["./run.sh", os.fspath(probe)], cwd=ROOT, env=env,
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            self.assertIn("REST_CONTINUATION_OK", result.stdout)
            self.assertEqual(effect.read_text(encoding="utf-8"),
                             "continued-once\n")

    def test_cetta_executes_quoted_batch_once(self):
        petta = self._petta_root()
        cetta = self._cetta_binary()
        if not cetta.is_file() or not (petta / "lib" / "lib_import.metta").is_file():
            self.skipTest("CeTTa/PeTTa checkouts are unavailable")
        with tempfile.TemporaryDirectory() as directory:
            directory = pathlib.Path(directory)
            effect = directory / "effect.log"
            probe = directory / "probe.metta"
            command = "printf 'effect-once\\n' >> %s" % shlex.quote(
                os.fspath(effect))
            probe.write_text(
                "!(println! (run-command-batch-once 424242 "
                "(quote ((shell %s)))))\n" % json.dumps(command),
                encoding="utf-8",
            )
            result = subprocess.run(
                [os.fspath(cetta), "--lang", "petta", "--import-mode",
                 "ancestor-walk", os.fspath(petta / "lib" / "lib_import.metta"),
                 os.fspath(ROOT / "src" / "skills.metta"), os.fspath(probe)],
                cwd=ROOT, env=self._cetta_env(), stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            self.assertEqual(effect.read_text(encoding="utf-8"),
                             "effect-once\n")

    def test_cetta_runs_timed_continuation(self):
        petta = self._petta_root()
        cetta = self._cetta_binary()
        if not cetta.is_file() or not (petta / "lib" / "lib_import.metta").is_file():
            self.skipTest("CeTTa/PeTTa checkouts are unavailable")
        with tempfile.TemporaryDirectory() as directory:
            directory = pathlib.Path(directory)
            effect = directory / "continued.log"
            probe = directory / "continuation.metta"
            command = "printf 'continued-once\\n' >> %s" % shlex.quote(
                os.fspath(effect))
            probe.write_text(
                "!(let* (($p (coordinate iteration 7 "
                "(coordinate loops 0 (coordinate sleep-interval 1 "
                "(coordinate last-results before "
                "(coordinate last-heartbeat 9 "
                "(coordinate active-policy agent "
                "(coordinate autonomous-ready 0 "
                "(coordinate pending-continuation "
                "(continuation-value (shell %s)) "
                "coordinates-empty))))))))) "
                "($resumed (applyTimedContinuation $p 1)) "
                "($_ (assert (== (loop-budget $resumed) 2))) "
                "($_ (assert (== (loop-pending-continuation $resumed) "
                "no-continuation)))) (println! REST_CONTINUATION_OK))\n"
                % json.dumps(command),
                encoding="utf-8",
            )
            files = [
                petta / "lib" / "lib_import.metta",
                petta / "lib" / "lib_patrick.metta",
                petta / "lib" / "lib_llm.metta",
                petta / "lib" / "lib_vector.metta",
                petta / "lib" / "lib_combinatorics.metta",
                ROOT / "lib_nal.metta", ROOT / "lib_nal7.metta",
                ROOT / "src" / "utils.metta",
                ROOT / "src" / "channels.metta",
                ROOT / "src" / "weak_process_core.metta",
                ROOT / "src" / "open_assemblage.metta",
                ROOT / "src" / "loop_policy.metta",
                ROOT / "src" / "skills.metta",
                ROOT / "src" / "memory.metta",
                ROOT / "src" / "attention_graph.metta",
                ROOT / "src" / "loop.metta", probe,
            ]
            result = subprocess.run(
                [os.fspath(cetta), "--lang", "petta", "--import-mode",
                 "ancestor-walk", *(os.fspath(path) for path in files)],
                cwd=ROOT, env=self._cetta_env(), stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            self.assertIn("REST_CONTINUATION_OK", result.stdout)
            self.assertEqual(effect.read_text(encoding="utf-8"),
                             "continued-once\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
