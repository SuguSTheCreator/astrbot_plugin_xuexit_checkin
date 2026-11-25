import json
import tempfile
import unittest
from pathlib import Path

from chaoxing.accounts import COOKIE_PREFIX, AccountStore


class TestCookieEncryption(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "accounts.json"

    def tearDown(self):
        self.dir.cleanup()

    def test_cookie_not_written_in_plaintext(self):
        store = AccountStore(self.path)
        store.bind("name:x", name="x", cookie="_uid=1; uf=SECRET")
        raw = self.path.read_text(encoding="utf-8")
        self.assertNotIn("SECRET", raw)
        self.assertIn(COOKIE_PREFIX, raw)

    def test_roundtrip(self):
        store = AccountStore(self.path)
        store.bind("name:x", name="x", cookie="_uid=1; uf=SECRET")
        again = AccountStore(self.path)
        self.assertEqual(again.get("name:x")["cookie"], "_uid=1; uf=SECRET")

    def test_key_file_created(self):
        store = AccountStore(self.path)
        store.bind("name:x", name="x", cookie="c=1")
        self.assertTrue((Path(self.dir.name) / "secret.key").exists())

    def test_legacy_plaintext_still_reads(self):
        self.path.write_text(json.dumps({
            "version": 1,
            "accounts": {"name:y": {"name": "y", "cookie": "_uid=9; uf=OLD"}},
        }), encoding="utf-8")
        store = AccountStore(self.path)
        self.assertEqual(store.get("name:y")["cookie"], "_uid=9; uf=OLD")

    def test_summary_has_no_cookie(self):
        store = AccountStore(self.path)
        store.bind("name:x", name="x", cookie="_uid=1; uf=SECRET")
        row = store.summary()[0]
        self.assertNotIn("cookie", row)


if __name__ == "__main__":
    unittest.main()
