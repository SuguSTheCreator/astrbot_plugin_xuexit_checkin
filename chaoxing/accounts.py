"""账号绑定存储：谁对应谁的 cookie，落盘持久化。"""
import json
import logging
import os
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

#: 密文前缀；没有前缀的当作历史明文，读的时候原样返回
COOKIE_PREFIX = "enc:v1:"


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


class AccountStore:
    """一个 JSON 文件保存所有绑定关系，写入用原子替换，权限尽量收紧。"""

    def __init__(self, path, key_path=None):
        self.path = Path(path)
        self.key_path = Path(key_path) if key_path else self.path.parent / "secret.key"
        self._fernet = None
        self.data = {"version": SCHEMA_VERSION, "accounts": {}}
        #: 加载时的问题，供自检展示；空串表示一切正常
        self.load_error = ""
        self.quarantined = ""
        self.decrypt_failed = 0
        self.invalid_records = 0
        #: 最近一次「记账写入」失败的原因；空串表示正常。自检会读它。
        self.last_write_error = ""
        self.load()

    # ---------- 加密 ----------
    def _cipher(self):
        """惰性初始化 Fernet；环境里没有 cryptography 就退化成明文。"""
        if self._fernet is not None:
            return self._fernet or None
        try:
            from cryptography.fernet import Fernet
        except Exception:
            self._fernet = False
            return None
        try:
            if not self.key_path.exists():
                self.key_path.parent.mkdir(parents=True, exist_ok=True)
                self.key_path.write_bytes(Fernet.generate_key())
                try:
                    os.chmod(self.key_path, 0o600)
                except OSError:
                    pass
            self._fernet = Fernet(self.key_path.read_bytes().strip())
        except Exception:
            self._fernet = False
            return None
        return self._fernet

    def _encrypt(self, value):
        cipher = self._cipher()
        if cipher is None or not value or str(value).startswith(COOKIE_PREFIX):
            return value
        try:
            return COOKIE_PREFIX + cipher.encrypt(str(value).encode()).decode()
        except Exception:
            return value

    def _decrypt(self, value):
        text = value if isinstance(value, str) else ""
        if not text.startswith(COOKIE_PREFIX):
            return value  # 历史明文，原样返回
        cipher = self._cipher()
        if cipher is None:
            logger.warning("[xuexit] 有密文但环境缺 cryptography，Cookie 读不出来")
            return ""
        try:
            return cipher.decrypt(text[len(COOKIE_PREFIX):].encode()).decode()
        except Exception:
            # 密钥换了 / 密文坏了：别静默变空串，让上层能报出来
            logger.warning("[xuexit] 一条 Cookie 解不开（密钥不匹配或密文损坏）")
            return ""

    def _quarantine(self):
        """把读不出来的账号文件挪走留证据，而不是原地覆盖。"""
        try:
            target = self.path.with_name(
                self.path.name + ".corrupt-" + time.strftime("%Y%m%d-%H%M%S"))
            os.replace(self.path, target)
            try:
                os.chmod(target, 0o600)
            except OSError:
                pass
            self.quarantined = str(target)
        except OSError:
            pass

    # ---------- 持久化 ----------
    def load(self):
        """读账号文件。坏了要降级，不能让整个插件起不来。

        解析失败 / 结构不对 → 把坏文件改名留证据，空账号启动，原因写进 load_error。
        单纯读不动（权限、占用）→ 只记原因，不动文件。
        """
        self.load_error = ""
        self.quarantined = ""
        self.decrypt_failed = 0
        self.invalid_records = 0
        if not self.path.exists():
            return self
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except ValueError as exc:
            self.load_error = "账号文件不是合法 JSON：" + str(exc)
            self._quarantine()
            logger.warning("[xuexit] %s（已留证据，按空账号启动）", self.load_error)
            return self
        except OSError as exc:
            self.load_error = "账号文件读不动：" + str(exc)
            logger.warning("[xuexit] %s", self.load_error)
            return self

        if isinstance(raw, dict) and "accounts" in raw:
            self.data = raw
        elif isinstance(raw, dict):
            self.data = {"version": SCHEMA_VERSION, "accounts": raw}
        else:
            self.load_error = "账号文件格式不对（顶层不是对象）"
            self._quarantine()
            logger.warning("[xuexit] %s（已留证据，按空账号启动）", self.load_error)
            return self

        accounts = self.data.get("accounts")
        if not isinstance(accounts, dict):
            self.load_error = "账号文件的 accounts 字段不是对象"
            self._quarantine()
            self.data = {"version": SCHEMA_VERSION, "accounts": {}}
            logger.warning("[xuexit] %s", self.load_error)
            return self

        # 内存里一律用明文；落盘时才加密
        for key in list(accounts):
            record = accounts[key]
            if not isinstance(record, dict):
                # 下游一律按 dict 用，留着会崩；剔掉并记数，原文件下次保存前仍在磁盘上
                self.invalid_records += 1
                accounts.pop(key, None)
                continue
            if isinstance(record.get("cookie"), str):
                original = record["cookie"]
                record["cookie"] = self._decrypt(original)
                if original.startswith(COOKIE_PREFIX) and not record["cookie"]:
                    self.decrypt_failed += 1
        if self.invalid_records:
            logger.warning("[xuexit] %d 条账号记录结构不对，已跳过", self.invalid_records)
        if self.decrypt_failed:
            logger.warning("[xuexit] %d 个账号的 Cookie 解不开，需要重新扫码", self.decrypt_failed)
        return self

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = json.loads(json.dumps(self.data))  # 深拷贝，别把明文写回去之前先改坏内存
        for record in snapshot.get("accounts", {}).values():
            if isinstance(record, dict) and isinstance(record.get("cookie"), str):
                record["cookie"] = self._encrypt(record["cookie"])
        payload = json.dumps(snapshot, ensure_ascii=False, indent=2)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent),
                                   prefix=".accounts-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        return self

    def save_best_effort(self):
        """记账式写入：失败只记录，不抛。

        用在「事情已经做完了，只是补记一笔」的场景（打卡成功后记时间、记体检）。
        这时候抛异常会把已经成功的结论翻成失败，比丢一条记录更糟。
        用户主动发起的写入（绑定、改 Cookie、撤回）仍然用 save()，失败必须报出来。
        """
        try:
            self.save()
            self.last_write_error = ""
            return True
        except Exception as exc:
            self.last_write_error = str(exc)
            logger.warning("[xuexit] 账号记账写入失败（不影响本次结论）：%s", exc)
            return False

    @property
    def crypto_enabled(self):
        """Cookie 是否真的在加密存放（环境缺 cryptography 时会退化成明文）。"""
        return self._cipher() is not None

    # ---------- 读写 ----------
    @property
    def accounts(self):
        return self.data.setdefault("accounts", {})

    def bind(self, key, name="", cookie="", uid="", nickname="", state_path="", owner=""):
        if not key:
            raise ValueError("绑定 key 不能为空")
        if not cookie:
            raise ValueError("cookie 不能为空")
        record = {
            "name": name or key,
            "cookie": cookie,
            "uid": str(uid or ""),
            "nickname": nickname or "",
            "state_path": state_path or "",
            "bound_at": _now(),
            "last_success": "",
            "status": "active",
            "owner": str(owner or ""),
        }
        self.accounts[key] = record
        self.save()
        return record

    def get(self, key):
        return self.accounts.get(key)

    def remove(self, key):
        existed = self.accounts.pop(key, None) is not None
        if existed:
            self.save()
        return existed

    def update_cookie(self, key, cookie, uid="", nickname=""):
        record = self.accounts.get(key)
        if record is None:
            return None
        record["cookie"] = cookie
        if uid:
            record["uid"] = str(uid)
        if nickname:
            record["nickname"] = nickname
        record["status"] = "active"
        record["bound_at"] = _now()
        self.save()
        return record

    def mark_success(self, key, date_str="", stage=""):
        record = self.accounts.get(key)
        if record is None:
            return None
        record["last_success"] = date_str or time.strftime("%Y-%m-%d")
        record["status"] = "active"
        if stage:
            record["last_stage"] = stage
            record["last_run_at"] = _now()
        self.save_best_effort()
        return record

    def set_owner(self, key, owner):
        """账号归属人（openid）。填了之后当事人 /status 才看得到自己的号。"""
        record = self.accounts.get(key)
        if record is None:
            return None
        record["owner"] = str(owner or "").strip()
        self.save()
        return record

    def set_health(self, key, status, message=""):
        """记一次体检结果，面板上显示用。"""
        record = self.accounts.get(key)
        if record is None:
            return None
        record["last_health"] = {
            "status": str(status or ""),
            "message": str(message or "")[:120],
            "at": _now(),
        }
        self.save_best_effort()
        return record

    def mark_expired(self, key):
        record = self.accounts.get(key)
        if record is None:
            return None
        record["status"] = "expired"
        self.save_best_effort()
        return record

    def find_by_uid(self, uid):
        for key, record in self.accounts.items():
            if record.get("uid") == str(uid):
                return key, record
        return None, None

    def find_by_name(self, name):
        for key, record in self.accounts.items():
            if record.get("name") == name:
                return key, record
        return None, None

    # ---------- 对外视图 ----------
    def summary(self):
        rows = []
        for key, record in self.accounts.items():
            rows.append({
                "key": key,
                "name": record.get("name", ""),
                "uid": record.get("uid", ""),
                "nickname": record.get("nickname", ""),
                "status": record.get("status", ""),
                "bound_at": record.get("bound_at", ""),
                "last_success": record.get("last_success", ""),
                "last_stage": record.get("last_stage", ""),
                "last_run_at": record.get("last_run_at", ""),
                "notify": bool(record.get("umo")),
                "owner": record.get("owner", ""),
                "last_health": record.get("last_health") or {},
            })
        return rows

    def __len__(self):
        return len(self.accounts)