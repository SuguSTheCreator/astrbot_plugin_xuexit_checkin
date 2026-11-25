"""账号绑定存储：谁对应谁的 cookie，落盘持久化。"""
import json
import os
import tempfile
import time
from pathlib import Path

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
            return ""
        try:
            return cipher.decrypt(text[len(COOKIE_PREFIX):].encode()).decode()
        except Exception:
            return ""

    # ---------- 持久化 ----------
    def load(self):
        if not self.path.exists():
            return self
        with open(self.path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if isinstance(raw, dict) and "accounts" in raw:
            self.data = raw
        elif isinstance(raw, dict):
            self.data = {"version": SCHEMA_VERSION, "accounts": raw}
        else:
            raise ValueError("账号文件格式不对")
        # 内存里一律用明文；落盘时才加密
        for record in self.data.get("accounts", {}).values():
            if isinstance(record, dict) and isinstance(record.get("cookie"), str):
                record["cookie"] = self._decrypt(record["cookie"])
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
        self.save()
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
        self.save()
        return record

    def mark_expired(self, key):
        record = self.accounts.get(key)
        if record is None:
            return None
        record["status"] = "expired"
        self.save()
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