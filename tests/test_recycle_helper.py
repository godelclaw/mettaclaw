import os
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from src.helper import recycle_requested


ROOT = Path(__file__).resolve().parents[1]


class RecycleRequestTests(unittest.TestCase):
    def test_operator_helper_uses_deployed_instance_name(self):
        # The request lands where run.sh reads it: under the instance name
        # run.sh uses, the checkout's own name unless one is configured.
        for instance, directory in (("pettaclaw-probe", "pettaclaw-probe"),
                                    (None, ROOT.name)):
            with tempfile.TemporaryDirectory() as state:
                env = {key: value for key, value in os.environ.items()
                       if key not in ("METTACLAW_INSTANCE",
                                      "METTACLAW_RECYCLE_REQUEST_PATH")}
                env.update(XDG_STATE_HOME=state,
                           METTACLAW_RECYCLE_WAIT_SECONDS="0")
                if instance:
                    env["METTACLAW_INSTANCE"] = instance
                subprocess.run(
                    ["bash", str(ROOT / "scripts" / "request_recycle.sh")],
                    env=env, capture_output=True, text=True, timeout=30)
                self.assertTrue(
                    (Path(state) / directory / "recycle.requested").is_file(),
                    sorted(str(p) for p in Path(state).rglob("*")))

    def test_disabled_without_a_configured_path(self):
        with mock.patch.dict(
            os.environ, {"METTACLAW_RECYCLE_REQUEST_PATH": ""}, clear=False
        ):
            result = recycle_requested()
            self.assertIs(type(result), int)
            self.assertEqual(result, 0)

    def test_flag_is_observed_without_consuming_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            flag = Path(tmp) / "recycle.requested"
            flag.write_text("request\n", encoding="utf-8")
            with mock.patch.dict(
                os.environ,
                {"METTACLAW_RECYCLE_REQUEST_PATH": str(flag)},
                clear=False,
            ):
                result = recycle_requested()
                self.assertIs(type(result), int)
                self.assertEqual(result, 1)
                self.assertTrue(flag.exists())

    def test_directory_at_flag_path_is_not_a_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                os.environ,
                {"METTACLAW_RECYCLE_REQUEST_PATH": tmp},
                clear=False,
            ):
                result = recycle_requested()
            self.assertIs(type(result), int)
            self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
