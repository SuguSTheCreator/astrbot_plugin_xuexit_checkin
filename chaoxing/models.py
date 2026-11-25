"""配置与结果数据模型。"""
import datetime
from dataclasses import dataclass, field
from typing import Any


def beijing_now():
    """返回北京时间（UTC+8），不依赖系统时区与 zoneinfo（兼容 Python 3.8）。"""
    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    return now_utc + datetime.timedelta(hours=8)


def _as_bool(value, default=True):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() not in ("0", "false", "no", "off", "")


@dataclass
class CheckinConfig:
    cookie: str
    form_id: str
    enc: str
    fid_enc: str = ""
    state_fid: str = ""
    uuid: str = ""
    submit_version: str = ""
    form_template: Any = ""
    location: str = ""
    base_url: str = "https://office.chaoxing.com"
    timeout: float = 20.0
    dry_run: bool = True
    state_path: str = ""
    webhook_url: str = ""
    extra_params: Any = ""
    fallback_form_data: Any = ""
    auto_sync: bool = True

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError("配置必须是 JSON 对象")

        def pick(*names, default=""):
            for name in names:
                if name in data and data[name] is not None:
                    return data[name]
            return default

        dry = pick("dry_run", "DRY_RUN", default=True)
        if not isinstance(dry, bool):
            dry = str(dry).strip().lower() not in ("0", "false", "no", "off")

        cfg = cls(
            cookie=str(pick("cookie", "COOKIE")),
            form_id=str(pick("form_id", "FORM_ID")),
            enc=str(pick("enc", "FORM_ENC")),
            fid_enc=str(pick("fid_enc", "FORM_FID_ENC")),
            state_fid=str(pick("state_fid", "STATE_FID")),
            uuid=str(pick("uuid", "UUID")),
            submit_version=str(pick("submit_version", "SUBMIT_VERSION")),
            form_template=pick("form_template", "FORM_TEMPLATE"),
            location=str(pick("location", "LOCATION")),
            base_url=str(pick("base_url", default="https://office.chaoxing.com")).rstrip("/"),
            timeout=float(pick("timeout", default=20.0)),
            dry_run=dry,
            state_path=str(pick("state_path", default="state.json")),
            webhook_url=str(pick("webhook_url", "WEBHOOK_URL")),
            extra_params=pick("extra_params", "EXTRA_PARAMS", default=""),
            fallback_form_data=pick("fallback_form_data", "FALLBACK_FORM_DATA", default=""),
            auto_sync=_as_bool(pick("auto_sync", "AUTO_SYNC", default=True), True),
        )
        if not cfg.cookie:
            raise ValueError("缺少 cookie")
        if not cfg.form_id:
            raise ValueError("缺少 form_id")
        if not cfg.enc:
            raise ValueError("缺少 enc")
        return cfg


@dataclass
class CheckinResult:
    ok: bool
    stage: str
    message: str
    detail: str = ""
    dry_run: bool = False
    skipped: bool = False
    synced: bool = False
    timestamp: str = field(
        default_factory=lambda: beijing_now().strftime("%Y-%m-%d %H:%M:%S")
    )

    def to_dict(self):
        return {
            "ok": self.ok,
            "stage": self.stage,
            "message": self.message,
            "detail": self.detail,
            "dry_run": self.dry_run,
            "skipped": self.skipped,
            "timestamp": self.timestamp,
        }

    def to_text(self):
        head = "✅" if self.ok else "❌"
        parts = [head + " " + self.message]
        if self.detail:
            parts.append("详情：" + self.detail)
        parts.append("时间：" + self.timestamp + ("（dry-run）" if self.dry_run else ""))
        return "\n".join(parts)
