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


class TestBestEffortWrites(unittest.TestCase):
    """记账写入失败不能把已经成功的结论翻成失败。"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_accounts_save_best_effort_swallows_and_records(self):
        store = AccountStore(Path(self.dir) / "accounts.json")
        store.bind("k", name="甲", cookie="_uid=1")
        # 把路径换成目录，写入必然失败
        store.path = Path(self.dir)
        self.assertFalse(store.save_best_effort())
        self.assertTrue(store.last_write_error)

    def test_mark_success_does_not_raise_when_write_fails(self):
        store = AccountStore(Path(self.dir) / "accounts.json")
        store.bind("k", name="甲", cookie="_uid=1")
        store.path = Path(self.dir)
        record = store.mark_success("k", date_str="2026-11-26", stage="submit")
        self.assertIsNotNone(record)
        self.assertEqual(record["last_success"], "2026-11-26")
        self.assertTrue(store.last_write_error)

    def test_set_health_does_not_raise_when_write_fails(self):
        store = AccountStore(Path(self.dir) / "accounts.json")
        store.bind("k", name="甲", cookie="_uid=1")
        store.path = Path(self.dir)
        self.assertIsNotNone(store.set_health("k", "ok", "fine"))
        self.assertTrue(store.last_write_error)

    def test_mark_expired_does_not_raise_when_write_fails(self):
        store = AccountStore(Path(self.dir) / "accounts.json")
        store.bind("k", name="甲", cookie="_uid=1")
        store.path = Path(self.dir)
        self.assertIsNotNone(store.mark_expired("k"))

    def test_user_initiated_save_still_raises(self):
        store = AccountStore(Path(self.dir) / "accounts.json")
        store.path = Path(self.dir)
        with self.assertRaises(Exception):
            store.bind("k", name="甲", cookie="_uid=1")

    def test_state_best_effort_swallows_and_records(self):
        d = os.path.join(self.dir, "isdir")
        os.makedirs(d, exist_ok=True)
        store = StateStore(d)
        self.assertFalse(store.save_best_effort({"a": 1}))
        self.assertTrue(store.last_write_error)

    def test_state_mark_success_does_not_raise(self):
        d = os.path.join(self.dir, "isdir2")
        os.makedirs(d, exist_ok=True)
        store = StateStore(d)
        store.mark_success("2026-11-26", {"ok": True})
        self.assertTrue(store.last_write_error)

    def test_best_effort_clears_error_on_success(self):
        store = AccountStore(Path(self.dir) / "accounts.json")
        store.bind("k", name="甲", cookie="_uid=1")
        store.path = Path(self.dir)
        store.save_best_effort()
        self.assertTrue(store.last_write_error)
        store.path = Path(self.dir) / "accounts.json"
        self.assertTrue(store.save_best_effort())
        self.assertEqual(store.last_write_error, "")


class TestAuditFailureVisibility(unittest.TestCase):
    def test_write_failure_is_counted_not_silent(self):
        from audit import AuditLog

        d = tempfile.mkdtemp()
        target = Path(d) / "isdir"
        target.mkdir()
        log = AuditLog(target)
        self.assertFalse(log.write("consent"))
        self.assertEqual(log.write_failures, 1)
        self.assertTrue(log.last_error)
        self.assertFalse(log.write("consent"))
        self.assertEqual(log.write_failures, 2)

    def test_write_success_keeps_zero_failures(self):
        from audit import AuditLog

        d = tempfile.mkdtemp()
        log = AuditLog(Path(d) / "audit.jsonl")
        self.assertTrue(log.write("consent"))
        self.assertEqual(log.write_failures, 0)
        self.assertEqual(log.last_error, "")


class TestContactsRobustness(unittest.TestCase):
    class _Plugin:
        def __init__(self, data_dir):
            self._data_dir = data_dir

    @staticmethod
    def _webui():
        """webui.py 用的是相对导入，必须挂在一个包下面才能 import。"""
        import importlib
        import sys
        import types

        root = str(Path(__file__).resolve().parent.parent)
        name = "_xuexit_under_test"
        if name not in sys.modules:
            pkg = types.ModuleType(name)
            pkg.__path__ = [root]
            sys.modules[name] = pkg
        return importlib.import_module(name + ".webui")

    def setUp(self):
        webui = self._webui()
        self._contacts_path = webui._contacts_path
        self._load_contacts = webui._load_contacts
        self.dir = tempfile.mkdtemp()
        self.plugin = self._Plugin(self.dir)
        self.path = self._contacts_path(self.plugin)

    def test_missing_file_is_clean(self):
        self.assertEqual(self._load_contacts(self.plugin), {})
        self.assertEqual(self.plugin._contacts_error, "")

    def test_corrupt_file_is_quarantined_and_reported(self):
        self.path.write_text("{ trunc", encoding="utf-8")
        self.assertEqual(self._load_contacts(self.plugin), {})
        self.assertTrue(self.plugin._contacts_error)
        self.assertTrue(self.plugin._contacts_quarantined)
        self.assertTrue(os.path.exists(self.plugin._contacts_quarantined))
        self.assertFalse(self.path.exists())

    def test_non_object_is_reported(self):
        self.path.write_text("[]", encoding="utf-8")
        self.assertEqual(self._load_contacts(self.plugin), {})
        self.assertIn("格式不对", self.plugin._contacts_error)

    def test_good_file_roundtrip(self):
        self.path.write_text('{"a":"甲"}', encoding="utf-8")
        self.assertEqual(self._load_contacts(self.plugin), {"a": "甲"})
        self.assertEqual(self.plugin._contacts_error, "")


class TestWriteSemanticsBoundary(unittest.TestCase):
    """固化「哪些算记账」的分类表。

    新增会写盘的方法时必须在这里归类，否则这条测试失败 ——
    让边界靠机器守，而不是靠人记得。
    """

    EXPECTED = {
        "chaoxing/accounts.py": {
            "save": {"bind", "remove", "update_cookie", "set_owner"},
            "save_best_effort": {"mark_success", "set_health", "mark_expired"},
        },
        "chaoxing/state.py": {
            "save": set(),
            "save_best_effort": {"mark_success"},
        },
    }

    def test_classification_matches(self):
        import ast

        root = Path(__file__).resolve().parent.parent
        for rel, expected in self.EXPECTED.items():
            tree = ast.parse((root / rel).read_text(encoding="utf-8"))
            found = {"save": set(), "save_best_effort": set()}
            for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
                for fn in [n for n in cls.body if isinstance(n, ast.FunctionDef)]:
                    if fn.name in ("save", "save_best_effort"):
                        continue  # 包装方法本身不算业务方法
                    for n in ast.walk(fn):
                        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                            if n.func.attr in found:
                                found[n.func.attr].add(fn.name)
            self.assertEqual(found, expected,
                             "%s 的写入语义分类变了，请确认是有意为之并更新此表" % rel)


if __name__ == "__main__":
    unittest.main()
