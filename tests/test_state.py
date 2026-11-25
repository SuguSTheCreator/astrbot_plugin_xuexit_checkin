import os
import tempfile
import unittest

from chaoxing.state import StateStore


class StateTest(unittest.TestCase):
    def test_mark_and_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(os.path.join(tmp, "state.json"))
            self.assertFalse(store.already_done("2026-11-17"))
            store.mark_success("2026-11-17", {"ok": True})
            self.assertTrue(store.already_done("2026-11-17"))
            self.assertFalse(store.already_done("2026-11-18"))
