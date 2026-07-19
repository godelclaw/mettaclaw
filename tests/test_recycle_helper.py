import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from src.helper import recycle_requested


class RecycleRequestTests(unittest.TestCase):
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
