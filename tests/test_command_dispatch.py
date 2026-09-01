import pathlib
import shutil
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("swipl"), "SWI-Prolog is required")
class CommandDispatchTests(unittest.TestCase):
    def test_turn_cache_prevents_effect_replay(self):
        result = subprocess.run(
            ["swipl", "-q", "-s", "tests/test_command_dispatch.pl",
             "-g", "run_tests,halt"],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
