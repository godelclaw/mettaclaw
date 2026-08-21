"""Require semantic witnesses from the real PeTTa runtime probes."""

import os
import pathlib
import re
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
ANSI_CONTROL = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


class RuntimeProbeTest(unittest.TestCase):
    PROBES = (
        ("tests/weak_process_core_probe.metta", "WEAK_PROCESS_CORE_OK"),
        ("tests/weak_process_episode_probe.metta", "WEAK_PROCESS_EPISODE_OK"),
        ("tests/shared_policy_turn_probe.metta", "SHARED_POLICY_TURN_OK"),
        ("tests/loop_policy_probe.metta", "LOOP_POLICY_OK"),
        ("tests/fuel_policy_probe.metta", "FUEL_POLICY_OK"),
        ("tests/rest_banking_probe.metta", "REST_BANKING_OK"),
        ("tests/rest_continuation_probe.metta", "REST_CONTINUATION_OK"),
        ("tests/context_sources_probe.metta", "CONTEXT_SOURCES_OK"),
        ("tests/iter_process_adapter_probe.metta", "ITER_PROCESS_ADAPTER_OK"),
    )

    def assert_witness(self, result, marker, engine):
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        witnessed = ANSI_CONTROL.sub("", result.stdout)
        self.assertRegex(
            witnessed,
            re.compile(r"^%s$" % re.escape(marker), re.MULTILINE),
            "%s exited successfully without reaching the semantic witness"
            % engine,
        )

    def test_each_probe_reaches_its_success_witness(self):
        petta_root = pathlib.Path(os.environ.get(
            "PETTA_ROOT", pathlib.Path.home() / "repos" / "PeTTa"))
        if not (petta_root / "run.sh").is_file():
            self.skipTest("PeTTa checkout is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            for probe, marker in self.PROBES:
                with self.subTest(probe=probe):
                    env = dict(os.environ)
                    env.update({
                        "METTACLAW_SKIP_INITIALIZE": "1",
                        "METTACLAW_ENGINE": "petta",
                        "METTACLAW_ENGINE_STATE_PATH": os.path.join(
                            directory, "engine"),
                        "METTACLAW_LOOP_MODE_PATH": os.path.join(
                            directory, "loop-mode.json"),
                        "METTACLAW_CHROMA_DIR": os.path.join(
                            directory, "chroma"),
                    })
                    result = subprocess.run(
                        ["./run.sh", probe], cwd=ROOT, env=env,
                        stdin=subprocess.DEVNULL, capture_output=True,
                        text=True, timeout=30,
                    )
                    self.assert_witness(result, marker, "PeTTa")

    def test_context_projection_crosses_cetta_provider_boundary(self):
        cetta = pathlib.Path(os.environ.get(
            "CETTA_BIN", pathlib.Path.home() / "repos" / "CeTTa" / "cetta"))
        if not cetta.is_file():
            self.skipTest("CeTTa executable is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ)
            env.update({
                "CETTA_BIN": os.fspath(cetta),
                "METTACLAW_SKIP_INITIALIZE": "1",
                "METTACLAW_ENGINE": "cetta",
                "METTACLAW_ENGINE_STATE_PATH": os.path.join(
                    directory, "engine"),
                "METTACLAW_CHROMA_DIR": os.path.join(directory, "chroma"),
            })
            result = subprocess.run(
                ["./run.sh", "tests/context_sources_probe.metta"],
                cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=30,
            )
            self.assert_witness(result, "CONTEXT_SOURCES_OK", "CeTTa")


if __name__ == "__main__":
    unittest.main(verbosity=2)
