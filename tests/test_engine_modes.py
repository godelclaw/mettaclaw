"""Persistent evaluator selection is explicit, atomic, and fail-closed."""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import engine_modes  # noqa: E402


class EngineModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_env = {
            name: os.environ.get(name) for name in (
                "METTACLAW_ENGINE",
                "METTACLAW_ACTIVE_ENGINE",
                "METTACLAW_ENGINE_STATE_PATH",
                "METTACLAW_ENGINE_FAILURE_PATH",
                "METTACLAW_RECYCLE_REQUEST_PATH",
            )
        }
        os.environ.pop("METTACLAW_ENGINE", None)
        os.environ["METTACLAW_ACTIVE_ENGINE"] = "petta"
        os.environ["METTACLAW_ENGINE_STATE_PATH"] = os.path.join(
            self.tmp.name, "state", "engine")
        os.environ["METTACLAW_ENGINE_FAILURE_PATH"] = os.path.join(
            self.tmp.name, "state", "engine-failure")
        os.environ["METTACLAW_RECYCLE_REQUEST_PATH"] = os.path.join(
            self.tmp.name, "state", "recycle.requested")

    def tearDown(self):
        for name, value in self.old_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self.tmp.cleanup()

    def test_absent_or_invalid_state_falls_back_to_petta(self):
        self.assertEqual(engine_modes.selected_engine(), "petta")
        os.makedirs(os.path.dirname(engine_modes._state_path()), exist_ok=True)
        with open(engine_modes._state_path(), "w", encoding="utf-8") as out:
            out.write("nonsense\n")
        self.assertEqual(engine_modes.selected_engine(), "petta")

    def test_alias_persists_canonical_engine(self):
        with mock.patch.object(engine_modes, "engine_available",
                               return_value=True):
            reply = engine_modes.set_engine("swi-petta")
        self.assertIn("already active", reply)
        with open(engine_modes._state_path(), encoding="utf-8") as stream:
            self.assertEqual(stream.read(), "petta\n")

    def test_requested_engine_does_not_change_active_process(self):
        with mock.patch.object(engine_modes, "engine_available",
                               return_value=True):
            reply = engine_modes.set_engine("cetta")
        self.assertIn("recycling", reply)
        self.assertEqual(engine_modes.selected_engine(), "cetta")
        self.assertEqual(engine_modes.active_engine(), "petta")
        self.assertIn("requested cetta", engine_modes.engine_view())

    def test_unavailable_engine_is_not_persisted(self):
        with mock.patch.object(engine_modes, "engine_available",
                               return_value=False):
            reply = engine_modes.set_engine("cetta")
        self.assertIn("unavailable", reply)
        self.assertFalse(os.path.exists(engine_modes._state_path()))

    def test_pleatta_is_disabled_with_an_explicit_notice(self):
        reply = engine_modes.set_engine("pleatta")
        self.assertIn("temporarily disabled", reply)
        self.assertFalse(os.path.exists(engine_modes._state_path()))
        with mock.patch.object(engine_modes, "engine_available",
                               return_value=True):
            self.assertIn("pleatta [disabled]", engine_modes.engines_view())

    def test_recycle_request_is_atomic_and_private(self):
        self.assertTrue(engine_modes.request_recycle())
        path = os.environ["METTACLAW_RECYCLE_REQUEST_PATH"]
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        with open(path, encoding="utf-8") as stream:
            self.assertIn("reason=engine-switch", stream.read())

    def test_last_engine_failure_is_visible_without_changing_selection(self):
        path = os.environ["METTACLAW_ENGINE_FAILURE_PATH"]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(
                "schema=1\nengine=cetta\nstatus=7\n"
                "reason=CeTTa process exited\n")
        self.assertEqual(engine_modes.selected_engine(), "petta")
        self.assertIn("last cetta failure", engine_modes.engine_view())
        self.assertIn("CeTTa process exited", engine_modes.engines_view())


if __name__ == "__main__":
    unittest.main(verbosity=2)
