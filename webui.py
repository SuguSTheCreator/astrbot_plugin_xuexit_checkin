"""插件 WebUI 后端：设置页接口。

页面通过 AstrBot 的插件页面桥接调用：
    GET  /<plugin>/settings   读取主账号与用户列表
    POST /<plugin>/settings   修改主账号 / 删除用户
"""
from __future__ import annotations

import time

from .policy import matrix as policy_matrix

#: 数据处理说明的版本号；文案改了就往后挪，面板据此提示「需要重新确认」
CONSENT_VERSION = "2026-11-24.1"

try:
    from quart import request
except Exception:  # pragma: no cover
    request = None


def _helper_pubkey_path():
    from pathlib import Path
    return Path("/AstrBot/data/plugin_data/astrbot_plugin_xuexit_checkin/helper_pubkey")


def _container_gateway():
    """读 /proc/net/route 里的默认网关，得到 docker 网桥地址。"""
    try:
        with open("/proc/net/route", "r", encoding="utf-8") as fh:
            for line in fh.readlines()[1:]:
                parts = line.split()
                if len(parts) > 2 and parts[1] == "00000000":
                    raw = parts[2]
                    return ".".join(str(int(raw[i:i + 2], 16)) for i in (6, 4, 2, 0))
    except Exception:
        pass
    return ""


def _contacts_path(plugin):
    from pathlib import Path

    return Path(plugin._data_dir) / "contacts.json"


def _load_contacts(plugin):
    import json

    try:
        return json.loads(_contacts_path(plugin).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _ok(data=None, message=""):
    return {"status": "ok", "message": message, "data": data or {}}


def _fail(message):
    return {"status": "error", "message": message, "data": {}}


class SettingsApi:
    def __init__(self, plugin):
        self.plugin = plugin

    # ---------- 读取 ----------
    async def get_settings(self):
        try:
            plugin = self.plugin
            admins = list(plugin.config.get("ADMIN_UMOS", []) or [])
            summary = list(plugin.config.get("SUMMARY_UMOS", []) or [])
            users = plugin.store.summary() if getattr(plugin, "store", None) else []
            return _ok({
                "admins": admins,
                "admin_ids": list(plugin.config.get("ADMIN_IDS", []) or []),
                "contacts": _load_contacts(plugin),
                "members": list(plugin.config.get("MEMBERS", []) or []),
                "member_all": bool(plugin.config.get("MEMBER_ALL", True)),
                "summary_umos": summary,
                "users": users,
                "enable": bool(plugin.config.get("ENABLE", True)),
                "dry_run": bool(plugin.config.get("DRY_RUN", False)),
                "auto_sync": bool(plugin.config.get("AUTO_SYNC", True)),
                "consent": bool(plugin.config.get("CONSENT_ACCEPTED", True)),
                "consent_at": str(plugin.config.get("CONSENT_AT", "") or ""),
                "consent_source": str(plugin.config.get("CONSENT_AT_SOURCE", "") or ""),
                "consent_version": str(plugin.config.get("CONSENT_VERSION", "") or ""),
                "allow_self_bind": bool(plugin.config.get("ALLOW_SELF_BIND", False)),
                "form_url_source": str(plugin.config.get("FORM_URL_SOURCE", "") or ""),
                "push_text_ok": str(plugin.config.get("PUSH_TEXT_OK", "") or ""),
                "push_text_fail": str(plugin.config.get("PUSH_TEXT_FAIL", "") or ""),
                "push_text_summary": str(plugin.config.get("PUSH_TEXT_SUMMARY", "") or ""),
                "form_url_days": int(plugin.config.get("FORM_URL_CHECK_DAYS", 30) or 0),
                "audit_enabled": bool(plugin.config.get("AUDIT_ENABLED", True)),
                "audit": self._audit_tail(15),
                "audit_count": self._audit_count(),
                "schedule": str(plugin.config.get("SCHEDULE_TIME", "")),
                "qr_fid": str(plugin.config.get("QR_FID", "")),
                "login_proxy": str(plugin.config.get("LOGIN_PROXY", "") or ""),
                "helper": {
                    "port": int(plugin.config.get("HELPER_PORT", 8898) or 8898),
                    "idle_exit": int(plugin.config.get("HELPER_IDLE_EXIT", 180) or 0),
                    "max_life": int(plugin.config.get("HELPER_MAX_LIFE", 1800) or 0),
                    "bind": str(plugin.config.get("HELPER_BIND", "") or "") or _container_gateway(),
                    "detected_bind": _container_gateway(),
                    "ssh": str(plugin.config.get("HELPER_SSH", "") or ""),
                },
                "hints": [
                    "打开方式：从 AstrBot 面板左侧「扩展功能」进入本页；直接输入网址或收藏夹打开不会加载数据。",
                    "只有把 AstrBot 装在云服务器时才需要「登录助手」；装在自己电脑上的话，这一块完全不用管，直接扫码。",
                    "SSH 目标怎么填：用公网 IP 访问面板时已自动填好；如果是 127.0.0.1 隧道访问，就填服务器的公网 IP。",
                    "找不到服务器 IP：阿里云/腾讯云控制台 → 实例列表 → 「公网 IP」那一列；宝塔面板首页右上角也显示；装在自己电脑上就填 127.0.0.1。",
                    "用户需要先在 QQ 里给机器人发过一句话，之后才能收到每日结果私聊。",
                    "没有私聊的用户，结果会合并到 SUMMARY_UMOS 指定的会话。",
                ],
            })
        except Exception as exc:
            return _fail("读取失败：" + str(exc))

    # ---------- 修改 ----------
    async def post_settings(self):
        if request is None:
            return _fail("当前环境不支持读取请求体")
        body = {}
        try:
            if hasattr(request, "get_json"):
                body = await request.get_json(force=True, silent=True)
            if not body:
                body = await request.json
        except Exception:
            body = body or {}
        if not isinstance(body, dict):
            return _fail("请求必须是 JSON 对象")

        action = str(body.get("action", "")).strip()
        try:
            if action == "add_admin":
                umo = str(body.get("umo", "")).strip()
                if not umo:
                    return _fail("UMO 不能为空")
                admins = list(self.plugin.config.get("ADMIN_UMOS", []) or [])
                if umo not in admins:
                    admins.append(umo)
                    self.plugin.config["ADMIN_UMOS"] = admins
                    self.plugin.config.save_config()
                return _ok({"admins": admins}, "已添加主账号")

            if action == "remove_admin":
                umo = str(body.get("umo", "")).strip()
                admins = [item for item in (self.plugin.config.get("ADMIN_UMOS", []) or []) if item != umo]
                self.plugin.config["ADMIN_UMOS"] = admins
                self.plugin.config.save_config()
                return _ok({"admins": admins}, "已移除")

            if action in ("add_member", "remove_member"):
                who = str(body.get("member", "")).strip()
                if not who:
                    return _fail("成员标识不能为空")
                members = list(self.plugin.config.get("MEMBERS", []) or [])
                if action == "add_member":
                    if who in members:
                        return _fail("已经在名单里了")
                    members.append(who)
                    msg = "已加入成员名单"
                else:
                    members = [item for item in members if item != who]
                    msg = "已移出成员名单"
                self.plugin.config["MEMBERS"] = members
                self.plugin.config.save_config()
                self._audit(action, target=who[:60])
                return _ok({"members": members}, msg)

            if action == "set_contact":
                import json

                key = str(body.get("key", "")).strip()
                name = str(body.get("name", "")).strip()[:40]
                if not key:
                    return _fail("缺少标识")
                data = _load_contacts(self.plugin)
                if name:
                    data[key] = name
                else:
                    data.pop(key, None)
                path = _contacts_path(self.plugin)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                try:
                    path.chmod(0o600)
                except OSError:
                    pass
                self._audit("set_contact", target=key[:40], detail=name)
                return _ok({"contacts": data}, "备注已保存")

            if action == "set_owner":
                key = str(body.get("key", "")).strip()
                owner = str(body.get("owner", "")).strip()
                if not key:
                    return _fail("缺少账号标识")
                if getattr(self.plugin, "store", None) is None:
                    return _fail("账号存储未初始化")
                record = self.plugin.store.set_owner(key, owner)
                if record is None:
                    return _fail("没找到该账号")
                self._audit("set_owner", target=str(record.get("name", ""))[:60],
                            detail=owner[:80])
                return _ok({"key": key, "owner": owner}, "归属已保存")

            if action == "check_form_source":
                try:
                    self.plugin._maybe_refresh_form_url(force=True)
                except Exception as exc:
                    return _fail("检查失败：" + str(exc))
                state = self.plugin._form_source_state()
                self._audit("check_form_source", detail=str(state.get("last_url", ""))[:80],
                            ok=bool(state.get("last_url")))
                return _ok(state, "已检查" if state.get("last_url") else "没读到链接")

            if action == "run_now":
                import asyncio as _asyncio

                key = str(body.get("key", "")).strip()
                store = getattr(self.plugin, "store", None)
                record = store.get(key) if store is not None else None
                if record is None:
                    return _fail("没找到该账号")
                from .chaoxing import run_once

                cfg = self.plugin._build_config(record)
                loop = _asyncio.get_running_loop()
                result = await loop.run_in_executor(None, lambda: run_once(cfg, force=True))
                status = await self.plugin._apply_result(key, record, result, notify_account=True)
                self._audit("run_now", target=str(record.get("name", ""))[:60],
                            detail=status + " " + str(result.message)[:80], ok=bool(result.ok))
                return _ok(
                    {"status": status, "ok": bool(result.ok), "message": result.message},
                    result.message,
                )

            if action == "health_check":
                import asyncio as _asyncio

                key = str(body.get("key", "")).strip()
                store = getattr(self.plugin, "store", None)
                record = store.get(key) if store is not None else None
                if record is None:
                    return _fail("没找到该账号")
                from .chaoxing.health import diagnose

                cfg = self.plugin._build_config(record, dry_run=True)
                loop = _asyncio.get_running_loop()
                result = await loop.run_in_executor(None, lambda: diagnose(cfg))
                store.set_health(key, result["status"], result["message"])
                self._audit("health_check", target=str(record.get("name", ""))[:60],
                            detail=result["status"] + " " + result["message"][:60],
                            ok=result["status"] == "ok")
                return _ok(result, result["message"])

            if action == "dry_run":
                import asyncio as _asyncio

                key = str(body.get("key", "")).strip()
                store = getattr(self.plugin, "store", None)
                record = store.get(key) if store is not None else None
                if record is None:
                    return _fail("没找到该账号")
                from .chaoxing import run_once

                cfg = self.plugin._build_config(record, dry_run=True)
                loop = _asyncio.get_running_loop()
                result = await loop.run_in_executor(None, lambda: run_once(cfg, force=True))
                self._audit("dry_run", target=str(record.get("name", ""))[:60],
                            detail=str(result.message)[:120], ok=bool(result.ok))
                return _ok(
                    {
                        "ok": bool(result.ok),
                        "stage": getattr(result, "stage", ""),
                        "message": result.message,
                    },
                    result.message,
                )

            if action == "remove_user":
                # 撤回同意 = 删除账号 + 清掉它的状态文件，否则"删了还在打"
                key = str(body.get("key", "")).strip()
                if not key:
                    return _fail("缺少用户标识")
                store = getattr(self.plugin, "store", None)
                if store is None:
                    return _fail("账号存储未初始化")
                record = store.get(key) or {}
                name = str(record.get("name", ""))
                state_path = str(record.get("state_path", "") or "")
                removed = store.remove(key)
                purged = []
                if state_path:
                    try:
                        import os as _os

                        if _os.path.isfile(state_path):
                            _os.remove(state_path)
                            purged.append(_os.path.basename(state_path))
                    except OSError:
                        pass
                self._audit("purge_user", target=name[:60] or key[:40],
                            detail="state=" + (",".join(purged) or "无"), ok=bool(removed))
                return _ok(
                    {"removed": bool(removed), "purged": purged},
                    "已撤回并清理" if removed else "没找到该用户",
                )

            if action == "set_public_key":
                key = str(body.get("key", "")).strip().replace("\r", "").split("\n")[0].strip()
                if not (key.startswith("ssh-ed25519 ") or key.startswith("ssh-rsa ")):
                    return _fail("公钥格式不对，应以 ssh-ed25519 开头")
                path = _helper_pubkey_path()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(key + "\n", encoding="utf-8")
                try:
                    path.chmod(0o644)
                except OSError:
                    pass
                return _ok({"installed": True}, "公钥已提交，服务器会在几秒内自动安装")

            if action == "test_push":
                targets = list(self.plugin.config.get("SUMMARY_UMOS", []) or [])
                if not targets:
                    targets = list(self.plugin.config.get("ADMIN_UMOS", []) or [])
                if not targets:
                    return _fail("还没有配置推送会话")
                sent = 0
                detail = []
                for umo in targets:
                    ok = await self.plugin._send_text(umo, "PING 推送通道测试 " + time.strftime("%H:%M:%S"))
                    detail.append({"umo": umo, "ok": bool(ok)})
                    if ok:
                        sent += 1
                return _ok({"delivered": sent, "total": len(targets), "detail": detail}, "已发送 %d/%d" % (sent, len(targets)))

            if action == "apply_form_url":
                url = str(body.get("url", "")).strip()
                if not url:
                    return _fail("先把表单链接粘进来")
                from .chaoxing.formlink import parse_form_url

                found, warnings = parse_form_url(url)
                missing = [k for k, v in found.items() if not v]
                if missing:
                    return _fail("这条网址缺少 " + "、".join(missing) +
                                 "，确认复制的是表单页而不是首页/登录页")
                mapping = {
                    "form_id": "FORM_ID",
                    "enc": "FORM_ENC",
                    "fid_enc": "FORM_FID_ENC",
                    "state_fid": "STATE_FID",
                }
                changed = {}
                for field, key in mapping.items():
                    self.plugin.config[key] = found[field]
                    changed[key] = found[field][:12] + "…"
                self.plugin.config.save_config()
                self._audit("apply_form_url", target=found["form_id"],
                            detail="enc=" + found["enc"][:10])
                return _ok({"changed": changed, "warnings": warnings}, "表单参数已更新")

            if action == "probe_channel":
                return _ok(await self._probe_channel())

            if action == "audit_tail":
                return _ok({"rows": self._audit_tail(int(body.get("limit", 30) or 30)),
                            "count": self._audit_count()})

            if action == "self_check":
                return _ok(await self._self_check())

            if action == "qr_start":
                name = str(body.get("name", "")).strip()
                if not name:
                    return _fail("名字不能为空")
                png, err = await self._qr_start(name)
                if err:
                    return _fail(err)
                return _ok({"name": name, "image": png})

            if action == "qr_poll":
                name = str(body.get("name", "")).strip()
                payload, err = await self._qr_poll(name)
                if err:
                    return _fail(err)
                return _ok(payload)

            if action in ("add_user", "update_user"):
                name = str(body.get("name", "")).strip()
                cookie = str(body.get("cookie", "")).strip()
                if not name:
                    return _fail("名字不能为空")
                if not cookie:
                    return _fail("Cookie 不能为空")
                key = str(body.get("key", "")).strip() or ("name:" + name)
                if getattr(self.plugin, "store", None) is None:
                    return _fail("账号存储未初始化")
                if action == "update_user" and self.plugin.store.get(key):
                    self.plugin.store.update_cookie(key, cookie, uid=body.get("uid", ""))
                    return _ok({"key": key}, "已更新 Cookie")
                from .chaoxing.runner import slugify

                state_path = str(self.plugin._data_dir / "state" / (slugify(name) + ".json"))
                self.plugin.store.bind(key, name=name, cookie=cookie,
                                       uid=body.get("uid", ""), nickname=body.get("nickname", ""),
                                       state_path=state_path,
                                       owner=str(body.get("owner", "") or ""))
                return _ok({"key": key}, "已添加用户")

            if action == "parse_identity":
                import re

                raw = str(body.get("text", ""))
                umo = ""
                sid = ""
                m = re.search(r"umo:\s*(\S+)", raw)
                if m:
                    umo = m.group(1)
                m2 = re.search(r"sender_?id:\s*(\S+)", raw, re.I)
                if m2:
                    sid = m2.group(1)
                if not sid:
                    m3 = re.search(r"([0-9A-Fa-f]{32})", raw)
                    if m3:
                        sid = m3.group(1)
                if not umo and not sid:
                    return _fail("没解析出 umo 或 sender_id，把 /whoami 的整段输出粘进来")
                umos = list(self.plugin.config.get("ADMIN_UMOS", []) or [])
                ids = list(self.plugin.config.get("ADMIN_IDS", []) or [])
                if umo and umo not in umos:
                    umos.append(umo)
                if sid and sid not in ids:
                    ids.append(sid)
                self.plugin.config["ADMIN_UMOS"] = umos
                self.plugin.config["ADMIN_IDS"] = ids
                self.plugin.config.save_config()
                return _ok({"admins": umos, "admin_ids": ids}, "已添加主账号")

            if action == "add_admin_id":
                sid = str(body.get("id", "")).strip()
                if not sid:
                    return _fail("openid 不能为空")
                ids = list(self.plugin.config.get("ADMIN_IDS", []) or [])
                if sid not in ids:
                    ids.append(sid)
                    self.plugin.config["ADMIN_IDS"] = ids
                    self.plugin.config.save_config()
                return _ok({"admin_ids": ids}, "已添加 openid")

            if action == "remove_admin_id":
                sid = str(body.get("id", "")).strip()
                ids = [x for x in (self.plugin.config.get("ADMIN_IDS", []) or []) if x != sid]
                self.plugin.config["ADMIN_IDS"] = ids
                self.plugin.config.save_config()
                return _ok({"admin_ids": ids}, "已移除")

            if action in ("add_summary", "remove_summary"):
                umo = str(body.get("umo", "")).strip()
                if not umo:
                    return _fail("会话标识不能为空")
                umos = list(self.plugin.config.get("SUMMARY_UMOS", []) or [])
                if action == "add_summary":
                    if umo not in umos:
                        umos.append(umo)
                else:
                    umos = [item for item in umos if item != umo]
                self.plugin.config["SUMMARY_UMOS"] = umos
                self.plugin.config.save_config()
                return _ok({"summary_umos": umos}, "已保存")

            if action == "set_summary":
                umos = body.get("umos", [])
                umos = [str(item).strip() for item in umos if str(item).strip()]
                self.plugin.config["SUMMARY_UMOS"] = umos
                self.plugin.config.save_config()
                return _ok({"summary_umos": umos}, "已保存汇总会话")

            if action == "set_consent":
                accepted = bool(body.get("consent", True))
                self.plugin.config["CONSENT_ACCEPTED"] = accepted
                if accepted:
                    self.plugin.config["CONSENT_AT"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    self.plugin.config["CONSENT_AT_SOURCE"] = "user"
                    self.plugin.config["CONSENT_VERSION"] = CONSENT_VERSION
                self.plugin.config.save_config()
                self._audit("consent", target="accept" if accepted else "withdraw",
                            detail=CONSENT_VERSION if accepted else "", ok=accepted)
                return _ok(
                    {
                        "consent": accepted,
                        "consent_at": self.plugin.config.get("CONSENT_AT", ""),
                        "consent_source": self.plugin.config.get("CONSENT_AT_SOURCE", ""),
                    },
                    "已记录" if accepted else "已取消同意",
                )

            if action == "set_options":
                changed = {}
                for key, cfg_key in (("enable", "ENABLE"), ("dry_run", "DRY_RUN"),
                                     ("auto_sync", "AUTO_SYNC"),
                                     ("allow_self_bind", "ALLOW_SELF_BIND"),
                                     ("audit_enabled", "AUDIT_ENABLED"),
                                     ("member_all", "MEMBER_ALL"),
                                     ("form_url_source", "FORM_URL_SOURCE"),
                                     ("push_text_ok", "PUSH_TEXT_OK"),
                                     ("push_text_fail", "PUSH_TEXT_FAIL"),
                                     ("push_text_summary", "PUSH_TEXT_SUMMARY"),
                                     ("form_url_days", "FORM_URL_CHECK_DAYS"),
                                     ("schedule", "SCHEDULE_TIME"), ("qr_fid", "QR_FID"),
                                     ("login_proxy", "LOGIN_PROXY"),
                                     ("helper_ssh", "HELPER_SSH"), ("helper_bind", "HELPER_BIND"),
                                     ("helper_port", "HELPER_PORT"),
                                     ("helper_idle", "HELPER_IDLE_EXIT"),
                                     ("helper_max", "HELPER_MAX_LIFE")):
                    if key not in body:
                        continue
                    value = body.get(key)
                    if cfg_key in ("ENABLE", "DRY_RUN", "AUTO_SYNC", "ALLOW_SELF_BIND",
                                   "AUDIT_ENABLED", "MEMBER_ALL"):
                        if isinstance(value, str):
                            value = value.strip().lower() in ("1", "true", "yes", "on")
                        else:
                            value = bool(value)
                    elif cfg_key in ("HELPER_PORT", "HELPER_IDLE_EXIT", "HELPER_MAX_LIFE",
                                     "FORM_URL_CHECK_DAYS"):
                        try:
                            value = int(value)
                        except (TypeError, ValueError):
                            continue
                    else:
                        value = str(value or "").strip()
                    self.plugin.config[cfg_key] = value
                    changed[cfg_key] = value
                if changed:
                    self.plugin.config.save_config()
                    self._audit("config_change", detail=", ".join(
                        "%s=%s" % (k, v) for k, v in changed.items()))
                return _ok({"changed": changed}, "已保存设置")

            return _fail("未知操作：" + action)
        except Exception as exc:
            return _fail("操作失败：" + str(exc))

    # ---------- 通道检测 ----------
    async def _probe_channel(self):
        import asyncio

        def _check():
            import requests

            url = "https://passport2.chaoxing.com/login"
            params = {"fid": str(self.plugin.config.get("QR_FID", "")), "newversion": "true"}
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0"}
            out = {"direct": False, "proxy": False}
            try:
                resp = requests.get(url, params=params, headers=headers, timeout=6)
                out["direct"] = resp.status_code == 200 and 'id="uuid"' in resp.text
            except Exception:
                pass
            proxy = str(self.plugin.config.get("LOGIN_PROXY", "") or "")
            if proxy:
                try:
                    resp = requests.get(url, params=params, headers=headers, timeout=8,
                                        proxies={"http": proxy, "https": proxy})
                    out["proxy"] = resp.status_code == 200 and 'id="uuid"' in resp.text
                except Exception:
                    pass
            return out

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _check)
        try:
            from astrbot.api import logger

            logger.info("[xuexit] probe_channel -> %s", result)
        except Exception:
            pass
        return result

    # ---------- 留痕 ----------
    def _audit(self, action, actor="webui", target="", detail="", ok=True):
        log = getattr(self.plugin, "audit", None)
        if log is None:
            return False
        if not bool(self.plugin.config.get("AUDIT_ENABLED", True)):
            return False
        return log.write(action, actor=actor, target=target, detail=detail, ok=ok)

    def _audit_tail(self, limit=15):
        log = getattr(self.plugin, "audit", None)
        return log.tail(limit) if log is not None else []

    def _audit_count(self):
        log = getattr(self.plugin, "audit", None)
        return log.count() if log is not None else 0

    # ---------- 自检 ----------
    @staticmethod
    def _parse_hostport(text):
        import re

        found = re.search(r"(\d{1,3}(?:\.\d{1,3}){3}|localhost|[A-Za-z0-9.-]+):(\d{1,5})", str(text or ""))
        if not found:
            return "", 0
        return found.group(1), int(found.group(2))

    async def _probe_tunnel(self):
        import asyncio
        import socket

        config = self.plugin.config
        host, port = self._parse_hostport(config.get("LOGIN_PROXY", ""))
        source = "登录代理"
        if not host:
            host = str(config.get("HELPER_BIND", "") or "") or _container_gateway()
            try:
                port = int(config.get("HELPER_PORT", 8898) or 8898)
            except (TypeError, ValueError):
                port = 8898
            source = "助手端口"

        proxy = str(config.get("LOGIN_PROXY", "") or "")

        def _try():
            # 第一步：TCP。注意 socat 中继就算电脑那头没上线，也会接受连接，
            # 所以「连得上」不代表通道可用，必须再走一次真实 HTTP。
            try:
                with socket.create_connection((host, port), timeout=1.5):
                    pass
            except Exception as exc:
                return False, False, type(exc).__name__ + ": " + str(exc)[:60]
            if not proxy:
                return True, True, "TCP 连得上"
            try:
                import requests

                resp = requests.get(
                    "https://passport2.chaoxing.com/login",
                    params={"fid": str(config.get("QR_FID", "")) or "39037", "newversion": "true"},
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0"},
                    proxies={"http": proxy, "https": proxy},
                    timeout=6,
                )
                ok = resp.status_code == 200 and 'id="uuid"' in resp.text
                if ok:
                    return True, True, "中继在，出口正常"
                return True, False, "中继在监听，但电脑那头没连上（HTTP %d）" % resp.status_code
            except Exception as exc:
                return True, False, "中继在监听，但请求超时或失败：" + type(exc).__name__

        tcp, http_ok, detail = await asyncio.get_running_loop().run_in_executor(None, _try)
        self._audit("probe_tunnel", target="%s:%s" % (host, port), detail=detail, ok=http_ok)
        return {"ok": http_ok, "tcp": tcp, "http": http_ok, "host": host,
                "port": port, "source": source, "detail": detail}

    async def _self_check(self):
        """一次性体检：配置、账号、留痕、通道、门卫矩阵。"""
        plugin = self.plugin
        config = plugin.config
        checks = []

        def add(name, level, detail):
            checks.append({"name": name, "level": level, "detail": detail})

        admins = list(config.get("ADMIN_UMOS", []) or [])
        ids = list(config.get("ADMIN_IDS", []) or [])
        if admins or ids:
            add("主账号白名单", "ok", "会话 %d 个 / openid %d 个" % (len(admins), len(ids)))
        else:
            add("主账号白名单", "error", "一个都没配 —— 门卫形同虚设，谁都能用全部命令")

        users = plugin.store.summary() if getattr(plugin, "store", None) else []
        expired = [u.get("name", "?") for u in users if u.get("status") == "expired"]
        if not users:
            add("超星账号", "error", "还没绑定任何账号，打卡无从谈起")
        elif expired:
            add("超星账号", "warn", "%d 个，其中过期：%s" % (len(users), "、".join(expired)))
        else:
            add("超星账号", "ok", "%d 个，全部正常" % len(users))

        store = getattr(plugin, "store", None)
        if store is not None:
            from pathlib import Path

            load_error = getattr(store, "load_error", "")
            quarantined = getattr(store, "quarantined", "")
            if load_error:
                detail = load_error
                if quarantined:
                    detail += "；坏文件已留证据：" + Path(quarantined).name
                add("账号文件", "error", detail)
            else:
                add("账号文件", "ok", "可读，结构正常")

            broken = int(getattr(store, "decrypt_failed", 0) or 0)
            invalid = int(getattr(store, "invalid_records", 0) or 0)
            if broken or invalid:
                parts = []
                if broken:
                    parts.append("%d 个 Cookie 解不开（密钥不匹配或密文损坏），需重新扫码" % broken)
                if invalid:
                    parts.append("%d 条记录结构不对，已跳过" % invalid)
                add("账号数据", "error", "；".join(parts))
            else:
                add("账号数据", "ok", "全部可解密，结构正常")

        accepted = bool(config.get("CONSENT_ACCEPTED", True))
        at = str(config.get("CONSENT_AT", "") or "")
        src = str(config.get("CONSENT_AT_SOURCE", "") or "")
        version = str(config.get("CONSENT_VERSION", "") or "")
        if accepted and at and src == "user":
            add("同意留痕", "ok", "%s（用户勾选，条款 %s）" % (at, version or "未标版本"))
        elif accepted and at:
            add("同意留痕", "warn", "%s（补记，不是本人勾选的时间）" % at)
        elif accepted:
            add("同意留痕", "error", "显示已同意但没有任何时间记录")
        else:
            add("同意留痕", "warn", "当前未同意 —— 按说明应停止处理并删除已存 Cookie")

        schedule = str(config.get("SCHEDULE_TIME", "") or "")
        add("打卡时间", "ok" if schedule else "error", schedule + " 起（窗口内随机）" if schedule else "未设置")

        for key, label in (("FORM_ID", "表单 ID"), ("FORM_ENC", "表单 enc"), ("UUID", "uuid")):
            value = str(config.get(key, "") or "")
            shown = (value[:18] + "…") if len(value) > 18 else (value or "空")
            add(label, "ok" if value else "error", shown)

        summary = list(config.get("SUMMARY_UMOS", []) or [])
        add("结果推送", "ok" if summary else "warn",
            "%d 个会话" % len(summary) if summary else "没配 —— 打卡成功也不会告诉你")

        if bool(config.get("DRY_RUN", False)):
            add("演练模式", "warn", "开着 = 每天只验证登录，不真提交")
        else:
            add("演练模式", "ok", "关着（会真提交）")
        if not bool(config.get("ENABLE", True)):
            add("总开关", "warn", "关着，今天不会打卡")

        tunnel = await self._probe_tunnel()
        addr = "%s:%s" % (tunnel["host"], tunnel["port"])
        if tunnel["ok"]:
            add("登录通道", "ok", "%s 可用（%s）：%s" % (addr, tunnel["source"], tunnel["detail"]))
        elif tunnel["tcp"]:
            add("登录通道", "warn", "%s 中继在，但出口不通：%s —— 助手没开？有人要重扫会失败" % (addr, tunnel["detail"]))
        else:
            add("登录通道", "warn", "%s 连不上：%s —— 有人要重扫会失败" % (addr, tunnel["detail"]))

        store = getattr(plugin, "store", None)
        if store is not None:
            if getattr(store, "crypto_enabled", False):
                add("Cookie 加密", "ok", "落盘为密文（secret.key 权限 600）")
            else:
                add("Cookie 加密", "warn", "环境缺少 cryptography，目前是明文存放")

        members = list(config.get("MEMBERS", []) or [])
        member_all = bool(config.get("MEMBER_ALL", True))
        add("成员", "ok" if members else "info",
            ("%d 人，%s" % (len(members), "全部权限" if member_all else "只能聊天"))
            if members else "还没有成员")
        self_bind = bool(config.get("ALLOW_SELF_BIND", False))
        gate_rows = policy_matrix(allow_self_bind=self_bind, has_members=bool(members),
                                  member_allow_all=member_all)
        add("自助绑定", "warn" if self_bind else "ok",
            "已开启：任何陌生人都能 /bind 给自己绑账号" if self_bind
            else "已关闭：只有主账号能发起绑定")

        levels = [c["level"] for c in checks]
        verdict = {
            "error": levels.count("error"),
            "warn": levels.count("warn"),
            "ok": levels.count("ok"),
        }
        payload = {
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "checks": checks,
            "verdict": verdict,
            "tunnel": tunnel,
            "gate": gate_rows,
        }
        self._audit("self_check", detail="error=%d warn=%d ok=%d" % (
            verdict["error"], verdict["warn"], verdict["ok"]))
        return payload

    # ---------- 扫码 ----------
    async def _qr_start(self, name):
        import base64

        sessions = getattr(self.plugin, "_web_qr", None)
        if sessions is None:
            sessions = {}
            setattr(self.plugin, "_web_qr", sessions)
        proxy = str(self.plugin.config.get("LOGIN_PROXY", "") or "")
        fid = str(self.plugin.config.get("QR_FID", "") or "")
        try:
            from .chaoxing import QrLoginSession

            qr = QrLoginSession(fid=fid, proxy=proxy)
            qr.refresh()
        except Exception as exc:
            return None, "生成二维码失败：" + str(exc)
        sessions[name] = qr
        return base64.b64encode(qr.qr_image).decode("ascii"), None

    async def _qr_poll(self, name):
        sessions = getattr(self.plugin, "_web_qr", {}) or {}
        qr = sessions.get(name)
        if qr is None:
            return None, "登录会话不存在或已过期，请重新生成"
        try:
            state = qr.poll()
        except Exception as exc:
            return None, "轮询失败：" + str(exc)
        if state.get("state") == "confirmed":
            store = getattr(self.plugin, "store", None)
            if store is not None:
                from .chaoxing.runner import slugify

                store.bind("name:" + name, name=name, cookie=qr.cookie_string(),
                           uid=state.get("uid", ""), nickname=state.get("nickname", ""),
                           state_path=str(self.plugin._data_dir / "state" / (slugify(name) + ".json")))
            sessions.pop(name, None)
            return {"state": "confirmed", "name": name, "uid": state.get("uid", "")}, None
        return {"state": state.get("state", "waiting"), "uid": state.get("uid", "")}, None