import json
import os
import tempfile
import unittest
from pathlib import Path

from chaoxing.accounts import AccountStore, COOKIE_PREFIX
from chaoxing.state import StateStore


class TestAccountStoreRobustness(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = Path(self.dir) / "accounts.json"

    def write(self, text):
        self.path.write_text(text, encoding="utf-8")

    def test_missing_file_is_empty(self):
        store = AccountStore(self.path)
        self.assertEqual(store.accounts, {})
        self.assertEqual(store.load_error, "")

    def test_truncated_json_degrades_not_raises(self):
        self.write('{"version":1,"accounts":{ trunc')
        store = AccountStore(self.path)
        self.assertEqual(store.accounts, {})
        self.assertTrue(store.load_error)
        self.assertTrue(store.quarantined, "坏文件应改名留证据")
        self.assertTrue(os.path.exists(store.quarantined))
        self.assertFalse(self.path.exists())

    def test_non_json_degrades(self):
        self.write("not json at all")
        store = AccountStore(self.path)
        self.assertEqual(store.accounts, {})
        self.assertTrue(store.load_error)

    def test_top_level_array_degrades(self):
        self.write("[]")
        store = AccountStore(self.path)
        self.assertEqual(store.accounts, {})
        self.assertIn("格式不对", store.load_error)

    def test_accounts_field_not_object_degrades(self):
        self.write('{"version":1,"accounts":[]}')
        store = AccountStore(self.path)
        self.assertEqual(store.accounts, {})
        self.assertTrue(store.load_error)

    def test_non_dict_record_is_skipped_not_crashing(self):
        self.write('{"version":1,"accounts":{"a":"notadict","b":{"cookie":"_uid=1"}}}')
        store = AccountStore(self.path)
        self.assertEqual(store.invalid_records, 1)
        self.assertNotIn("a", store.accounts)
        self.assertIn("b", store.accounts)
        for record in store.accounts.values():
            self.assertIsInstance(record, dict)

    def test_broken_ciphertext_is_counted(self):
        self.write(json.dumps({"version": 1, "accounts": {
            "a": {"cookie": COOKIE_PREFIX + "GARBAGE"}}}))
        store = AccountStore(self.path)
        self.assertEqual(store.decrypt_failed, 1)
        self.assertEqual(store.accounts["a"]["cookie"], "")

    def test_good_file_roundtrip_has_no_errors(self):
        store = AccountStore(self.path)
        store.bind("k", name="甲", cookie="_uid=1; uf=abc")
        store.save()
        again = AccountStore(self.path)
        self.assertEqual(again.load_error, "")
        self.assertEqual(again.decrypt_failed, 0)
        self.assertEqual(again.accounts["k"]["cookie"], "_uid=1; uf=abc")

    def test_reload_resets_counters(self):
        self.write("[]")
        store = AccountStore(self.path)
        self.assertTrue(store.load_error)
        store.load()
        self.assertEqual(store.load_error, "")
        self.assertEqual(store.invalid_records, 0)


class TestStateStoreRobustness(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "state.json")

    def test_truncated_state_returns_empty(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{ trunc")
        self.assertEqual(StateStore(self.path).load(), {})

    def test_array_state_returns_empty(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("[]")
        self.assertEqual(StateStore(self.path).load(), {})


if __name__ == "__main__":
    unittest.main()
