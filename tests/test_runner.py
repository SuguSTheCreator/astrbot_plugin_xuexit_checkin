"""多账号 runner 测试。"""
import json
import os
import tempfile

from chaoxing.models import CheckinResult
from chaoxing.runner import (
    load_accounts,
    load_accounts_dir,
    merge_account,
    prepare,
    run_all,
    slugify,
)


def test_merge_defaults_and_override():
    defaults = {"form_id": "123456", "enc": "abc", "state_path": "state/default.json"}
    account = {"name": "张三", "cookie": "c1"}
    cfg = merge_account(defaults, account)
    assert cfg.form_id == "123456"
    assert cfg.cookie == "c1"
    assert cfg.state_path == "state/default.json"


def test_account_overrides_default():
    defaults = {"form_id": "1", "enc": "abc", "state_path": "a.json"}
    cfg = merge_account(defaults, {"cookie": "c", "form_id": "2"})
    assert cfg.form_id == "2"


def test_meta_keys_not_passed_to_config():
    cfg = merge_account({"form_id": "1", "enc": "abc"}, {"cookie": "c", "name": "x", "enabled": True})
    assert cfg.cookie == "c"


def test_slugify_keeps_chinese_and_sanitizes():
    assert slugify("张三") == "张三"
    assert slugify("a/b") == "a_b"
    assert slugify("") == "account0"


def test_prepare_generates_unique_state_paths():
    entries = [{"name": "张三"}, {"name": "李四"}]
    prepared = prepare(entries, {}, state_dir="state")
    paths = [item["state_path"] for item in prepared]
    assert paths[0] != paths[1]
    assert paths[0].startswith("state" + os.sep) or paths[0].startswith("state/")


def test_load_accounts_object_shape():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "accounts.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"defaults": {"form_id": "1"}, "accounts": [{"name": "a"}]}, fh)
        defaults, accounts = load_accounts(path)
        assert defaults["form_id"] == "1"
        assert accounts[0]["name"] == "a"


def test_load_accounts_list_shape():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "accounts.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump([{"name": "a"}], fh)
        defaults, accounts = load_accounts(path)
        assert defaults == {}
        assert len(accounts) == 1


def test_load_accounts_dir_uses_file_stem():
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "zhangsan.json"), "w", encoding="utf-8") as fh:
            json.dump({"cookie": "c"}, fh)
        defaults, accounts = load_accounts_dir(tmp)
        assert defaults == {}
        assert accounts[0]["name"] == "zhangsan"


def test_run_all_isolates_failure():
    def fake_runner(config, force=False):
        if config.cookie == "bad":
            raise RuntimeError("boom")
        return CheckinResult(ok=True, stage="submit", message="提交成功")

    accounts = [{"name": "a", "cookie": "good"}, {"name": "b", "cookie": "bad"}]
    outcomes = run_all(accounts, {"form_id": "1", "enc": "x"}, runner=fake_runner,
                       state_dir="state")
    assert outcomes[0].ok is True
    assert outcomes[1].ok is False
    assert "boom" in outcomes[1].error


def test_run_all_skips_disabled():
    called = []

    def fake_runner(config, force=False):
        called.append(config.cookie)
        return CheckinResult(ok=True, stage="submit", message="ok")

    accounts = [{"name": "a", "cookie": "c1", "enabled": False}, {"name": "b", "cookie": "c2"}]
    outcomes = run_all(accounts, {"form_id": "1", "enc": "x"}, runner=fake_runner)
    assert outcomes[0].skipped is True
    assert called == ["c2"]


def test_run_all_applies_dry_run():
    seen = {}

    def fake_runner(config, force=False):
        seen["dry_run"] = config.dry_run
        return CheckinResult(ok=True, stage="dry_run", message="ok", dry_run=True)

    run_all([{"name": "a", "cookie": "c"}], {"form_id": "1", "enc": "x"},
            runner=fake_runner, dry_run=True)
    assert seen["dry_run"] is True
