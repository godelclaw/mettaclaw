import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_godel_receipt_replay as replay  # noqa: E402


class ReceiptReplayPromptTest(unittest.TestCase):
    def test_prompt_distinguishes_proposals_returns_and_withheld_suffix(self):
        prompt = replay.replay_prompt("identity")
        self.assertIn("proposals are not actions", prompt)
        self.assertIn("returned means only", prompt)
        self.assertIn("withheld/deferred commands did not run", prompt)
        self.assertIn("partial(send-file failed", prompt)
        self.assertIn("unexecuted suffix", prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
