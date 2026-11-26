"""多账号批量执行：逐个跑，单条失败不影响其他账号。"""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .models import CheckinConfig, CheckinResult
from .service import run_once

META_KEYS = ("name", "enabled", "notify_umos", "remark")


@dataclass
class AccountOutcome:
    name: str
    ok: bool
    result: Optional[CheckinResult] = None
    error: str = ""
    skipped: bool = False

    def to_dict(self):
        data = {"name": self.name, "ok": self.ok, "skipped": self.skipped}
        if self.result is not None:
            data["result"] = self.result.to_dict()
        if self.error:
            data["error"] = self.error
        return data

    def to_text(self):
        head = "OK  " if self.ok else "FAIL"
        if self.skipped:
            return head + " " + self.name + "：已停用，跳过"
        if self.result is not None:
            return head + " " + self.name + "：" + self.result.message
        return head + " " + self.name + "：" + (self.error or "未知错误")


def _strip_meta(account):
    return {k: v for k, v in (account or {}).items() if k not in META_KEYS}


def merge_account(defaults, account):
    """把 defaults 与单个账号合并成 CheckinConfig（账号字段优先）。"""
    merged = dict(defaults or {})
    merged.update({k: v for k, v in _strip_meta(account).items() if v is not None})
    return CheckinConfig.from_dict(merged)


def slugify(name, index=0):
    keep = []
    for ch in str(name or ""):
        if ch.isalnum() or ch in "-_":
            keep.append(ch)
        elif ch in " \t/\\":
            keep.append("_")
    text = "".join(keep).strip("_")
    return text or ("account%d" % index)


def load_accounts(path):
    """读取账号文件，返回 (defaults, accounts)。

    支持两种写法：
      {"defaults": {...}, "accounts": [{...}, ...]}
      [{...}, {...}]                     （纯数组，无 defaults）
    """
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    if isinstance(raw, list):
        return {}, raw
    if not isinstance(raw, dict):
        raise ValueError("账号文件必须是 JSON 对象或数组")
    defaults = raw.get("defaults") or {}
    accounts = raw.get("accounts") or []
    if not isinstance(defaults, dict):
        raise ValueError("defaults 必须是对象")
    if not isinstance(accounts, list):
        raise ValueError("accounts 必须是数组")
    return defaults, accounts


def load_accounts_dir(directory):
    """目录模式：每个 *.json 是一个账号文件，按文件名排序。"""
    base = Path(directory)
    if not base.is_dir():
        raise ValueError("账号目录不存在：" + str(directory))
    accounts = []
    for path in sorted(base.glob("*.json")):
        with open(path, encoding="utf-8") as fh:
            entry = json.load(fh)
        if not isinstance(entry, dict):
            raise ValueError("账号文件必须是对象：" + path.name)
        entry = dict(entry)
        entry.setdefault("name", path.stem)
        entry.setdefault("_source", str(path))
        accounts.append(entry)
    return {}, accounts


def prepare(accounts, defaults, state_dir=None):
    """补全 state_path：没写的按账号名生成，避免多人共用同一个状态文件。"""
    prepared = []
    for index, account in enumerate(accounts):
        entry = dict(account)
        name = entry.get("name") or ("account%d" % index)
        entry["name"] = name
        if not entry.get("state_path"):
            filename = slugify(name, index) + ".json"
            entry["state_path"] = str(Path(state_dir) / filename) if state_dir else filename
        prepared.append(entry)
    return prepared


def run_all(accounts, defaults=None, force=False, runner=None, state_dir=None, dry_run=None):
    """逐条执行账号列表，返回 AccountOutcome 列表。"""
    if runner is None:
        runner = run_once
    items = prepare(accounts, defaults or {}, state_dir=state_dir)
    outcomes = []
    for index, entry in enumerate(items):
        name = entry.get("name") or ("account%d" % index)
        if entry.get("enabled") is False:
            outcomes.append(AccountOutcome(name=name, ok=True, skipped=True))
            continue
        try:
            config = merge_account(defaults, entry)
            if dry_run is not None:
                config.dry_run = dry_run
            result = runner(config, force=force)
            outcomes.append(AccountOutcome(name=name, ok=bool(result.ok), result=result))
        except Exception as exc:  # 单个账号失败不影响整体
            outcomes.append(AccountOutcome(name=name, ok=False, error=str(exc)))
    return outcomes
