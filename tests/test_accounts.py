"""账号绑定存储测试。"""
import os
import tempfile

import pytest

from chaoxing.accounts import AccountStore


def _store():
    tmp = tempfile.mkdtemp()
    return AccountStore(os.path.join(tmp, "accounts.json"))


def test_bind_and_get():
    s = _store()
    s.bind("openid:abc", name="张三", cookie="c=1", uid="100000001", nickname="小张")
    rec = s.get("openid:abc")
    assert rec["cookie"] == "c=1"
    assert rec["uid"] == "100000001"
    assert rec["status"] == "active"


def test_bind_requires_cookie():
    s = _store()
    with pytest.raises(ValueError):
        s.bind("k", cookie="")


def test_persist_and_reload():
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "accounts.json")
    s = AccountStore(path)
    s.bind("k1", name="a", cookie="c1")
    again = AccountStore(path)
    assert again.get("k1")["cookie"] == "c1"


def test_remove():
    s = _store()
    s.bind("k1", cookie="c")
    assert s.remove("k1") is True
    assert s.remove("k1") is False
    assert s.get("k1") is None


def test_update_cookie_resets_status():
    s = _store()
    s.bind("k1", cookie="old")
    s.mark_expired("k1")
    assert s.get("k1")["status"] == "expired"
    s.update_cookie("k1", "new")
    assert s.get("k1")["status"] == "active"
    assert s.get("k1")["cookie"] == "new"


def test_mark_success():
    s = _store()
    s.bind("k1", cookie="c")
    s.mark_success("k1", "2026-11-20")
    assert s.get("k1")["last_success"] == "2026-11-20"


def test_find_by_uid_and_name():
    s = _store()
    s.bind("k1", name="张三", cookie="c", uid="111")
    assert s.find_by_uid("111")[0] == "k1"
    assert s.find_by_name("张三")[0] == "k1"
    assert s.find_by_uid("999") == (None, None)


def test_summary_hides_cookie():
    s = _store()
    s.bind("k1", name="张三", cookie="secret", uid="111")
    rows = s.summary()
    assert len(rows) == 1
    assert "cookie" not in rows[0]
    assert rows[0]["name"] == "张三"
