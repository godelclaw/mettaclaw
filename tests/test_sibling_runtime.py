"""Sibling control follows the engine-neutral live service."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import sibling  # noqa: E402


class SiblingRuntimeTests(unittest.TestCase):
    def test_godel_runtime_is_not_tied_to_a_retired_engine(self):
        self.assertEqual(sibling._CLAWS["godel"]["unit"],
                         "pettaclaw-godel.service")
        self.assertNotIn("pleatta", sibling._CLAWS["godel"]["unit"])

    def test_lila_observes_the_engine_neutral_godel_service(self):
        with mock.patch.object(sibling, "_me", return_value="lila"), \
             mock.patch.object(sibling, "_systemctl",
                               return_value=(0, "active")) as systemctl:
            status = sibling.sibling_status()
        systemctl.assert_called_once_with(
            "is-active", "pettaclaw-godel.service")
        self.assertIn("Gödel: active", status)


if __name__ == "__main__":
    unittest.main(verbosity=2)
