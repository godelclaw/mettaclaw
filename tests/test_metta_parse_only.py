import os
import pathlib
import shutil
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PETTA_ROOT = pathlib.Path(
    os.environ.get("PETTA_ROOT", pathlib.Path.home() / "repos" / "PeTTa")
)


@unittest.skipUnless(shutil.which("swipl") and PETTA_ROOT.is_dir(),
                     "SWI-Prolog and PeTTa are required")
class CriticalMeTTaParseTests(unittest.TestCase):
    def test_loop_and_attention_graph_parse_without_evaluation(self):
        helper = ROOT / "scripts" / "metta_parse_only.pl"
        for relative in ("src/loop.metta", "src/attention_graph.metta"):
            with self.subTest(relative=relative):
                result = subprocess.run(
                    ["swipl", "--stack_limit=1g", "-q", "-s", str(helper),
                     "--", str(PETTA_ROOT), str(ROOT / relative)],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
