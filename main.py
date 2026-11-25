"""AstrBot 插件入口：扫码绑定 + 每日打卡 + 结果推送。

壳只做三件事：读 WebUI 配置、调度、把结果发到会话；
协议逻辑都在 chaoxing/ 里（纯 Python，CLI 与插件共用）。
"""
import asyncio
import json
import random
import re
import time
import traceback
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Image
from astrbot.api.star import Context, Star, StarTools

from .adapters.webhook import send_webhook
from .audit import AuditLog
from .policy import GUEST_COMMANDS
from .policy import gate as policy_gate
from .policy import identity as policy_identity
from .webui import SettingsApi
from .chaoxing import CheckinConfig, run_once
from .chaoxing.health import classify
from .chaoxing.accounts import AccountStore
from .chaoxing.models import beijing_now
from .chaoxing.qrlogin import (
    STATE_CONFIRMED,
    STATE_EXPIRED,
    STATE_SCANNED,
    QrLoginSession,
    QrLoginError,
)

PLUGIN_NAME = "astrbot_plugin_xuexit_checkin"
DEFAULT_SCHEDULE = "08:10"
DEFAULT_LOGIN_TTL = 300
# 兼容旧引用；真正的判定在 policy.gate()，不要在这里加命令
ALLOWED_FOR_USERS = set(GUEST_COMMANDS) | {"bind"}
DEFAULT_QR_FID = "39037"


def _sender_id(event):
    try:
        return str(event.get_sender_id())
    except Exception:
        return ""


def _as_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _as_list(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _slug(text, fallback="account"):
    keep = []
    for ch in str(text or ""):
        if ch.isalnum() or ch in "-_":
            keep.append(ch)
        elif ch in " \t/\\":
            keep.append("_")
    return "".join(keep).strip("_") or fallback


class XuexitCheckinPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._task = None
        self._pending = {}
        self._data_dir = self._resolve_data_dir()
        self._store = AccountStore(self._data_dir / "accounts.json")
        self.store = self._store  # 供 WebUI 层访问
        self.audit = AuditLog(self._data_dir / "audit.jsonl")
        self._normalize_consent()

    # ---------------- 基础设施 ----------------
    def _resolve_data_dir(self):
        try:
            base = Path(StarTools.get_data_dir(PLUGIN_NAME))
        except Exception:
            base = Path(__file__).resolve().parent / "data"
        base.mkdir(parents=True, exist_ok=True)
        (base / "state").mkdir(parents=True, exist_ok=True)
        (base / "qr").mkdir(parents=True, exist_ok=True)
        return base

    def _get(self, key, default=""):
        try:
            return self.config.get(key, default)
        except Exception:
            return default

    def _defaults(self):
        return {
            "form_id": str(self._get("FORM_ID", "")),
            "enc": str(self._get("FORM_ENC", "")),
            "fid_enc": str(self._get("FORM_FID_ENC", "")),
            "state_fid": str(self._get("STATE_FID", "")),
            "uuid": str(self._get("UUID", "")),
            "submit_version": str(self._get("SUBMIT_VERSION", "")),
            "form_template": self._get("FORM_TEMPLATE", ""),
            "fallback_form_data": str(self._get("FALLBACK_FORM_DATA", "")),
            "location": str(self._get("LOCATION", "")),
        }

    def _build_config(self, record, dry_run=False):
        params = self._defaults()
        overrides = record.get("overrides") or {}
        params.update(overrides)
        return CheckinConfig(
            cookie=str(record.get("cookie", "")),
            form_id=params.get("form_id", ""),
            enc=params.get("enc", ""),
            fid_enc=params.get("fid_enc", ""),
            state_fid=params.get("state_fid", ""),
            uuid=params.get("uuid", ""),
            submit_version=params.get("submit_version", ""),
            form_template=params.get("form_template", ""),
            fallback_form_data=params.get("fallback_form_data", ""),
            location=params.get("location", ""),
            dry_run=dry_run,
            state_path=record.get("state_path") or str(self._data_dir / "state" / "default.json"),
            webhook_url=str(self._get("WEBHOOK_URL", "")),
            auto_sync=bool(self._get("AUTO_SYNC", True)),
        )

    def _member_umos(self):
        """成员名单：面板里手工加的 MEMBERS + 通过聊天绑定过的 umo。"""
        found = []
        try:
            found.extend(str(key)[4:] for key in self._store.accounts
                         if str(key).startswith("umo:"))
        except Exception:
            pass
        for item in _as_list(self._get("MEMBERS", [])):
            if item not in found:
                found.append(item)
        return found

    def _identity(self, umo, sender_id=""):
        """统一身份判定：所有命令、门卫、自检都走这一个入口。"""
        return policy_identity(
            umo,
            sender_id,
            self._get("ADMIN_UMOS", []),
            self._get("ADMIN_IDS", []),
            self._member_umos(),
        )

    def _is_admin(self, umo, sender_id=""):
        """命令内部的管理员判定。

        和门卫保持同一口径：MEMBER_ALL 打开时，成员等同于主账号，
        否则会出现「门卫放行、命令自己却说没权限」的怪事。
        """
        role, _ = self._identity(umo, sender_id)
        if role == "admin":
            return True
        return role == "member" and _as_bool(self._get("MEMBER_ALL", True), True)

    def _allow_self_bind(self):
        return _as_bool(self._get("ALLOW_SELF_BIND", False), False)

    def _log(self, action, **fields):
        """统一留痕入口：关掉 AUDIT_ENABLED 就真的不写，避免变成死开关。"""
        if not _as_bool(self._get("AUDIT_ENABLED", True), True):
            return False
        return self.audit.write(action, **fields)

    def _normalize_consent(self):
        """同意时间补齐。

        历史 bug：默认就是「已同意」，从来没被勾选过，于是 CONSENT_AT 一直是空，
        等于这条留痕根本没生效。这里补记一个时间，并用 CONSENT_AT_SOURCE=backfill
        标明是补的，不伪造「用户当时同意过」。
        """
        try:
            accepted = _as_bool(self._get("CONSENT_ACCEPTED", True), True)
            at = str(self._get("CONSENT_AT", "") or "").strip()
            if accepted and not at:
                self.config["CONSENT_AT"] = time.strftime("%Y-%m-%d %H:%M:%S")
                self.config["CONSENT_AT_SOURCE"] = "backfill"
                self.config.save_config()
                self._log("consent_backfill", detail="默认开启但无同意时间，补记")
        except Exception:
            logger.warning("[xuexit] normalize consent failed: %s", traceback.format_exc())

    async def _run(self, config, force=False):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: run_once(config, force=force))

    async def _send_text(self, umo, text):
        try:
            result = await self.context.send_message(umo, MessageChain().message(text))
            if result is False:
                logger.error("[xuexit] send text to %s rejected by platform", umo)
                return False
            logger.info("[xuexit] sent %d chars to %s ok=%s", len(text), umo, result)
            return True
        except Exception:
            logger.error("[xuexit] send text to %s failed: %s", umo, traceback.format_exc(limit=2))
            return False

    async def _send_image(self, umo, path):
        try:
            await self.context.send_message(umo, MessageChain(chain=[Image.fromFileSystem(str(path))]))
            return True
        except Exception:
            logger.error("[xuexit] send image to %s failed: %s", umo, traceback.format_exc(limit=2))
            return False

    # ---------------- 生命周期 ----------------
    def _register_webui(self):
        api = SettingsApi(self)
        for endpoint, method, handler, desc in (
            ("settings", "GET", api.get_settings, "读取打卡设置"),
            ("settings", "POST", api.post_settings, "保存打卡设置"),
        ):
            route = "/" + PLUGIN_NAME + "/" + endpoint
            try:
                self.context.register_web_api(route, handler, [method], desc)
                logger.info("[xuexit] registered %s %s", method, route)
            except Exception:
                logger.error("[xuexit] register web api failed: %s", traceback.format_exc())

    async def initialize(self):
        logger.info("[xuexit] loaded, %d account(s)", len(self._store))
        self._register_webui()
        asyncio.create_task(self._catch_up(), name=PLUGIN_NAME + ".catchup")
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._scheduler_loop(), name=PLUGIN_NAME + ".scheduler")

    async def terminate(self):
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        for item in list(self._pending.values()):
            item["task"].cancel()

    # ---------------- 调度 ----------------
    def _seconds_until_next(self):
        import datetime

        now = beijing_now()
        hour, minute = self._parse_schedule()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += datetime.timedelta(days=1)
        return (target - now).total_seconds()

    def _parse_schedule(self):
        raw = str(self._get("SCHEDULE_TIME", DEFAULT_SCHEDULE)).strip()
        try:
            hour_text, minute_text = raw.split(":", 1)
            hour, minute = int(hour_text), int(minute_text)
            if 0 <= hour < 24 and 0 <= minute < 60:
                return hour, minute
        except (ValueError, TypeError):
            pass
        return 8, 10

    def _form_source_state(self):
        path = self._data_dir / "form_source.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_form_source_state(self, data):
        try:
            path = self._data_dir / "form_source.json"
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _maybe_refresh_form_url(self, force=False):
        """从远程文本里读表单链接；变了就自动换参数。

        只在到点时查（默认 30 天），失败不影响打卡。
        """
        source = str(self._get("FORM_URL_SOURCE", "") or "").strip()
        if not source:
            return
        try:
            days = int(self._get("FORM_URL_CHECK_DAYS", 30) or 30)
        except (TypeError, ValueError):
            days = 30
        state = self._form_source_state()
        now = time.time()
        last = float(state.get("checked_at", 0) or 0)
        if not force and days > 0 and now - last < days * 86400:
            return
        url = ""
        try:
            import requests

            resp = requests.get(source, timeout=10,
                                headers={"User-Agent": "xuexit-form-source/1.0"})
            if resp.status_code == 200:
                import re

                found = re.search(r"https?://[^\s\"'<>]+", resp.text or "")
                if found:
                    url = found.group(0)
        except Exception as exc:
            logger.warning("[xuexit] 读取远程表单链接失败：%s", exc)
        changed = False
        if url:
            from .chaoxing.formlink import parse_form_url

            params, _warnings = parse_form_url(url)
            if all(params.values()) and str(params["form_id"]) != str(self._get("FORM_ID", "")):
                for field, key in (("form_id", "FORM_ID"), ("enc", "FORM_ENC"),
                                   ("fid_enc", "FORM_FID_ENC"), ("state_fid", "STATE_FID")):
                    self.config[key] = params[field]
                self.config.save_config()
                changed = True
                self._log("form_url_refresh", target=params["form_id"],
                          detail="enc=" + params["enc"][:10])
                asyncio.create_task(self._notify_admin(
                    "FORM_REFRESH 表单链接已自动更新（formId=%s）" % params["form_id"]))
        state["checked_at"] = now
        state["last_url"] = url
        state["changed"] = changed
        self._save_form_source_state(state)

    def _done_today(self, record):
        """今天是否已经成功过。抓不到日期就当作没做过（宁可多做一次，不可漏做）。"""
        if _as_bool(self._get("DRY_RUN", False), False):
            return False
        today = beijing_now().strftime("%Y-%m-%d")
        return str(record.get("last_success", ""))[:10] == today

    async def _catch_up(self):
        """启动补跑：今天还没打的账号，开机后补一次（08:00-21:00 之间）。

        以前不看状态就排期，每次重启都要先随机睡 0~40 分钟再发现「其实已经打过了」，
        日志里那串「等待 N 秒后执行」就是空转。这里先筛一遍，没活干就直接退出。
        """
        await asyncio.sleep(30)
        try:
            now = beijing_now()
            if not (8 <= now.hour < 21):
                return
            if not _as_bool(self._get("ENABLE", True), True):
                return
            pending = [key for key, record in self._store.accounts.items()
                       if record.get("status") != "disabled" and not self._done_today(record)]
            if not pending:
                logger.info("[xuexit] catch-up skip: 今天都已成功（%d 个账号）",
                            len(self._store.accounts))
                return
            logger.info("[xuexit] catch-up start: %d 个待打", len(pending))
            await self._run_all()
            logger.info("[xuexit] catch-up done")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.error("[xuexit] catch-up error: %s", traceback.format_exc())

    async def _scheduler_loop(self):
        while True:
            try:
                delay = self._seconds_until_next()
                logger.info("[xuexit] next run in %s seconds", int(delay))
                await asyncio.sleep(max(5.0, delay))
                if not _as_bool(self._get("ENABLE", True), True):
                    await asyncio.sleep(60)
                    continue
                await self._run_all()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error("[xuexit] scheduler error: %s", traceback.format_exc())
                await asyncio.sleep(120)

    def _plan_delays(self, count):
        """把 count 个账号随机铺在一段窗口内，避免同一时刻集中请求。"""
        window = max(60, int(self._get("SCHEDULE_WINDOW_MINUTES", 40) or 40) * 60)
        if count <= 0:
            return []
        if count > window:
            return [random.randint(0, window) for _ in range(count)]
        return sorted(random.sample(range(0, window), count))

    async def _run_all(self):
        try:
            self._maybe_refresh_form_url()
        except Exception:
            logger.warning("[xuexit] refresh form url failed: %s", traceback.format_exc())
        total = len(self._store.accounts)
        entries = [(k, r) for k, r in list(self._store.accounts.items())
                   if r.get("status") != "disabled" and not self._done_today(r)]
        if not entries:
            logger.info("[xuexit] 今天没有需要打卡的账号（共 %d 个，已完成或已停用）", total)
            return
        if total > len(entries):
            logger.info("[xuexit] 跳过 %d 个今天已完成的账号", total - len(entries))
        delays = self._plan_delays(len(entries))
        started = time.monotonic()
        outcomes = []
        failed = []
        for (key, record), delay in zip(entries, delays):
            name = record.get("name") or key
            wait = started + delay - time.monotonic()
            if wait > 0:
                logger.info("[xuexit] %s 等待 %d 秒后执行", name, int(wait))
                await asyncio.sleep(wait)
            try:
                result = await self._run(self._build_config(record))
                await self._apply_result(key, record, result, notify_account=True)
                outcomes.append((name, result.ok, result.message))
                if not result.ok:
                    failed.append((key, record))
            except Exception as exc:
                outcomes.append((name, False, str(exc)))
                failed.append((key, record))
                await self._notify_admin("FAIL " + name + " - " + str(exc))
        if failed:
            delay_min = int(self._get("RETRY_DELAY_MINUTES", 35) or 35)
            logger.info("[xuexit] %d 个账号失败，%d 分钟后重试一次", len(failed), delay_min)
            await asyncio.sleep(max(60, delay_min * 60))
            for key, record in failed:
                name = record.get("name") or key
                try:
                    result = await self._run(self._build_config(record))
                    if result.ok:
                        self._store.mark_success(key, stage=result.stage)
                        await self._notify_account(record, "RETRY OK " + name + " - " + result.message)
                        for idx, item in enumerate(outcomes):
                            if item[0] == name:
                                outcomes[idx] = (name, True, result.message)
                                break
                except Exception as exc:
                    logger.error("[xuexit] retry %s failed: %s", name, exc)

        summary = "checkin " + beijing_now().strftime("%Y-%m-%d") + ": %d/%d ok" % (
            sum(1 for _, ok, _ in outcomes if ok), len(outcomes))
        delivered = 0
        targets = _as_list(self._get("SUMMARY_UMOS", []))
        for umo in targets:
            if await self._send_text(umo, summary):
                delivered += 1
        if targets:
            logger.info("[xuexit] summary delivered %d/%d", delivered, len(targets))
        logger.info("[xuexit] %s", summary)

    async def _apply_result(self, key, record, result, notify_account=False):
        """统一处理一次执行结果：记状态、记体检、发通知。

        定时打卡、手动打卡、面板「立即」都走这里，避免三处各写一套。
        返回分类结果（ok / cookie / form / ...）。
        """
        name = record.get("name") or key
        if result.ok:
            self._store.mark_success(key, stage=result.stage)
            self._store.set_health(key, "ok", result.message)
            if notify_account and not getattr(result, "skipped", False):
                await self._notify_account(record, "OK " + name + " - " + result.message)
            return "ok"

        status, tag, action = classify(getattr(result, "stage", ""), result.message)
        if tag == "NEED_RELOGIN":
            self._store.mark_expired(key)
        self._store.set_health(key, status, result.message)
        text = tag + " " + name + " - " + result.message
        if action:
            text += "\n建议：" + action
        await self._notify_admin(text)
        return status

    def _umo_for(self, record):
        """账号本人的会话地址。

        面板扫码绑的账号没有 umo，但填了「归属 openid」。
        用 openid 去已有名单里反查同平台的 umo，就能给他本人发私聊。
        """
        umo = str(record.get("umo") or "").strip()
        if umo:
            return umo
        owner = str(record.get("owner") or "").strip()
        if not owner:
            return ""
        pool = _as_list(self._get("ADMIN_UMOS", [])) + _as_list(self._get("SUMMARY_UMOS", []))
        for item in pool:
            if item.endswith(":" + owner):
                return item
        return ""

    async def _notify_account(self, record, text):
        umo = self._umo_for(record)
        if umo:
            await self._send_text(umo, text)

    async def _notify_admin(self, text):
        for umo in _as_list(self._get("ADMIN_UMOS", [])):
            await self._send_text(umo, text)

    # ---------------- 扫码绑定 ----------------
    async def _start_login(self, event, name, target_key, origin_umo):
        if target_key in self._pending:
            return "这个账号已经在等待扫码了，先扫完或等它过期。"
        try:
            qr = QrLoginSession(fid=str(self._get("QR_FID", DEFAULT_QR_FID)),
                            proxy=str(self._get("LOGIN_PROXY", "") or ""))
            png = qr.refresh()
        except Exception as exc:
            return "ERR:二维码生成失败：" + str(exc)
        tmp = self._data_dir / "qr" / ("%s-%s.jpg" % (_slug(name), random.randint(1000, 9999)))
        tmp.write_bytes(png)
        ttl = int(self._get("LOGIN_TTL_SECONDS", DEFAULT_LOGIN_TTL) or DEFAULT_LOGIN_TTL)
        task = asyncio.create_task(self._poll_login(name, target_key, origin_umo, qr, tmp, ttl))
        self._pending[target_key] = {"task": task, "name": name, "origin": origin_umo}
        return tmp

    async def _poll_login(self, name, target_key, origin_umo, qr, image_path, ttl):
        import time

        deadline = time.time() + ttl
        last_state = ""
        try:
            while time.time() < deadline:
                await asyncio.sleep(1.5)
                info = qr.poll()
                state = info.get("state")
                if state == STATE_CONFIRMED:
                    record = self._store.bind(
                        target_key,
                        name=name,
                        cookie=qr.cookie_string(),
                        uid=info.get("uid", ""),
                        nickname=info.get("nickname", ""),
                    )
                    record["umo"] = origin_umo
                    record["state_path"] = str(self._data_dir / "state" / (_slug(name) + ".json"))
                    self._store.save()
                    await self._send_text(origin_umo, "BOUND " + name + " · UID " + str(info.get("uid", "")))
                    await self._notify_admin("BOUND " + name + " · UID " + str(info.get("uid", "")))
                    return
                if state == STATE_EXPIRED:
                    await self._send_text(origin_umo, "二维码已过期，请重新发送 /login " + name)
                    return
                if state == STATE_SCANNED and last_state != STATE_SCANNED:
                    await self._send_text(origin_umo, "已扫码，请在手机上点确认")
                last_state = state
            await self._send_text(origin_umo, "二维码超时未确认，请重新发送 /login " + name)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.error("[xuexit] poll login failed: %s", traceback.format_exc())
            await self._send_text(origin_umo, "扫码过程出错，请重试")
        finally:
            self._pending.pop(target_key, None)
            try:
                image_path.unlink()
            except OSError:
                pass

    # ---------------- 门卫 ----------------
    @filter.event_message_type(filter.EventMessageType.ALL, priority=100)
    async def cmd_gate(self, event: AstrMessageEvent):
        """非管理员只能使用打卡相关指令，其他消息一律吞掉，避免误触其他插件。"""
        umo = getattr(event, "unified_msg_origin", "")
        text = (getattr(event, "message_str", "") or "").strip()
        if not text:
            # 某些平台把 @ 和正文分开，message_str 会是空；退回平台方法再取一次
            try:
                text = str(event.get_message_str() or "").strip()
            except Exception:
                text = ""
        role, _why = self._identity(umo, _sender_id(event))
        woken = bool(getattr(event, "is_at_or_wake_command", False))
        decision = policy_gate(
            text, role,
            allow_self_bind=self._allow_self_bind(),
            member_allow_all=_as_bool(self._get("MEMBER_ALL", True), True),
            bare=woken,
        )
        # 群聊里框架可能没判定为「在叫机器人」，指令处理器就不会执行；
        # 我们自己回一句，免得同学发了命令却石沉大海。
        if (
            decision["allow"]
            and decision["command"]
            and role != "admin"
            and not bool(getattr(event, "is_at_or_wake_command", True))
        ):
            await self._fallback_reply(event, umo, decision["command"])
            return
        if role != "admin" and (not decision["allow"] or decision["command"]):
            logger.info(
                "[xuexit] gate role=%s who=%s text=%r allow=%s at_wake=%s",
                role, umo, text[:40], decision["allow"],
                getattr(event, "is_at_or_wake_command", "?"),
            )
        if decision["allow"]:
            return
        if decision["command"]:
            self._log(
                "gate_deny",
                actor=str(umo)[:80],
                target=decision["command"],
                detail=decision["reason"],
                ok=False,
            )
        event.stop_event()

    async def _fallback_reply(self, event, umo, command):
        """框架不执行指令时的兜底回复（只处理给普通用户开放的那几条）。"""
        if command == "whoami":
            lines = ["umo: " + str(umo)]
            sid = _sender_id(event)
            if sid:
                lines.append("sender_id: " + sid)
            await self._send_text(umo, "\n".join(lines))
        elif command == "checkin_bind":
            await self._send_text(umo, "当前会话 UMO（填进 ADMIN_UMOS）：\n" + str(umo))
        elif command == "status":
            rows = self._store.summary()
            mine = [row for row in rows if row.get("key") == "umo:" + str(umo)]
            if mine:
                await self._send_text(umo, "你绑定了 %d 个账号：%s" % (
                    len(mine), "、".join(str(r.get("name")) for r in mine)))
            else:
                await self._send_text(umo, "你还没有绑定账号，找主账号帮你扫一次码。")
        elif command == "bind":
            await self._send_text(umo, "请在私聊里发送 /bind 完成绑定（群里发不了二维码）。")

    @filter.command("notify_test")
    async def cmd_notify_test(self, event: AstrMessageEvent):
        """给汇总会话发一条测试消息，确认推送通道正常（仅主账号）。"""
        targets = _as_list(self._get("SUMMARY_UMOS", [])) or _as_list(
            self._get("ADMIN_UMOS", [])
        )
        if not targets:
            yield event.plain_result("还没有配置汇总会话")
            return
        ok = 0
        for umo in targets:
            if await self._send_text(umo, "PING 推送通道正常 " + beijing_now().strftime("%H:%M:%S")):
                ok += 1
        yield event.plain_result("已发送 %d/%d 个会话" % (ok, len(targets)))

    @filter.command("whoami")
    async def cmd_whoami(self, event: AstrMessageEvent):
        """打印身份信息（用来拿 openid / 会话标识）。"""
        lines = []
        lines.append("umo: " + str(getattr(event, "unified_msg_origin", "")))
        sid = _sender_id(event)
        if sid:
            lines.append("sender_id: " + sid)
        mo = getattr(event, "message_obj", None)
        for attr in ("sender", "raw_message", "session_id", "message_id"):
            if mo is not None and hasattr(mo, attr):
                lines.append(attr + ": " + str(getattr(mo, attr))[:160])
        for attr in ("openid", "user_openid"):
            if hasattr(event, attr):
                lines.append("event." + attr + ": " + str(getattr(event, attr)))
        yield event.plain_result("\n".join(lines))

    # ---------------- 命令 ----------------
    @filter.command("login")
    async def cmd_login(self, event: AstrMessageEvent):
        parts = (event.message_str or "").strip().split()
        name = parts[1] if len(parts) > 1 else ""
        umo = getattr(event, "unified_msg_origin", "")
        if not self._is_admin(umo, _sender_id(event)):
            yield event.plain_result("只有管理员可以发起绑定。")
            return
        if not name:
            yield event.plain_result("用法：/login 张三")
            return
        image = await self._start_login(event, name, "name:" + name, umo)
        if isinstance(image, str) and image.startswith("ERR:"):
            yield event.plain_result(image[4:])
            return
        yield event.image_result(str(image))
        yield event.plain_result("请把这张码发给 " + name + "，让他用学习通扫（" + str(self._get("LOGIN_TTL_SECONDS", DEFAULT_LOGIN_TTL)) + " 秒内有效）")

    @filter.command("bind")
    async def cmd_bind(self, event: AstrMessageEvent):
        umo = getattr(event, "unified_msg_origin", "")
        sender = getattr(event, "get_sender_id", lambda: "")() or "me"
        parts = (event.message_str or "").strip().split()
        name = parts[1] if len(parts) > 1 else ("用户" + str(sender)[-4:])
        image = await self._start_login(event, name, "umo:" + umo, umo)
        if isinstance(image, str) and image.startswith("ERR:"):
            yield event.plain_result(image[4:])
            return
        yield event.image_result(str(image))
        yield event.plain_result("用学习通扫上面这张码，扫完点确认")

    @filter.command("status")
    async def cmd_status(self, event: AstrMessageEvent):
        umo = getattr(event, "unified_msg_origin", "")
        rows = self._store.summary()
        if self._is_admin(umo, _sender_id(event)):
            lines = ["共 %d 个账号" % len(rows)]
            for row in rows:
                lines.append("- %s | %s | %s | 上次成功 %s" % (
                    row["name"], row["status"] or "active",
                    "UID " + row["uid"] if row["uid"] else "无 UID",
                    row["last_success"] or "从未"))
        else:
            sid = _sender_id(event)
            mine = [r for r in rows
                    if r.get("key") == "umo:" + umo or (sid and r.get("owner") == sid)]
            lines = ["你绑定了 " + str(len(mine)) + " 个账号"]
            for row in mine:
                lines.append("- %s | %s | 上次成功 %s" % (
                    row["name"], row["status"] or "active", row["last_success"] or "从未"))
        yield event.plain_result("\n".join(lines))

    @filter.command("unbind")
    async def cmd_unbind(self, event: AstrMessageEvent):
        umo = getattr(event, "unified_msg_origin", "")
        if not self._is_admin(umo, _sender_id(event)):
            yield event.plain_result("只有管理员可以解绑。")
            return
        parts = (event.message_str or "").strip().split()
        if len(parts) < 2:
            yield event.plain_result("用法：/unbind 张三")
            return
        name = parts[1]
        removed = []
        for key, record in list(self._store.accounts.items()):
            if record.get("name") == name or key == "name:" + name:
                state_path = str(record.get("state_path", "") or "")
                self._store.remove(key)
                if state_path:
                    try:
                        Path(state_path).unlink()
                    except OSError:
                        pass
                removed.append(key)
        self._log("unbind", actor=str(umo)[:80], target=name,
                         detail=", ".join(removed) if removed else "not found", ok=bool(removed))
        yield event.plain_result("已解绑：" + (", ".join(removed) if removed else "没找到 " + name))

    @filter.command("checkin")
    async def cmd_checkin(self, event: AstrMessageEvent):
        umo = getattr(event, "unified_msg_origin", "")
        parts = (event.message_str or "").strip().split()
        if not self._is_admin(umo, _sender_id(event)):
            yield event.plain_result("只有管理员可以手动打卡。")
            return
        target = parts[1] if len(parts) > 1 else ""
        done = []
        for key, record in list(self._store.accounts.items()):
            name = record.get("name") or key
            if target and name != target:
                continue
            try:
                result = await self._run(self._build_config(record), force=True)
                if result.ok:
                    self._store.mark_success(key)
                self._log("checkin_manual", actor=str(umo)[:80], target=name,
                                 detail=str(result.message)[:200], ok=bool(result.ok))
                done.append(name + "：" + result.message)
            except Exception as exc:
                done.append(name + "：执行失败 " + str(exc))
        if not done:
            yield event.plain_result("没有匹配的账号")
            return
        yield event.plain_result("\n".join(done))

    @filter.command("checkin_bind")
    async def cmd_checkin_bind(self, event: AstrMessageEvent):
        umo = getattr(event, "unified_msg_origin", "")
        yield event.plain_result("当前会话 UMO（填进 ADMIN_UMOS）：\n" + str(umo))