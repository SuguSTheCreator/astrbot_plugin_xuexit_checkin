"""门卫策略：纯函数，插件 / WebUI / 测试共用同一份判定。

历史问题：判定散在 cmd_gate 的白名单、每个命令里的 _is_admin(umo)、WebUI 的文案里，
三处口径不一致（例如 /login 只按 umo 判断，而命中的可能是 openid 白名单）。
这里收敛成 identity() + gate() 两个纯函数，任何地方要判定都调这里。
"""

ADMIN = "admin"
MEMBER = "member"
GUEST = "guest"

#: 非主账号也能用的指令（只读、只涉及自己）
GUEST_COMMANDS = ("status", "whoami", "checkin_bind")
#: 自助绑定指令：是否放行由 ALLOW_SELF_BIND 决定
SELF_BIND_COMMAND = "bind"

#: 已知命令名（唤醒前缀被框架吃掉后，剩下的是裸命令名）
KNOWN_COMMANDS = frozenset((
    "bind", "checkin", "checkin_bind", "login",
    "notify_test", "status", "unbind", "whoami",
))

#: 自检表格里展示的命令
MATRIX_COMMANDS = (
    "/status", "/whoami", "/bind", "/checkin",
    "/login", "/unbind", "/notify_test", "你好",
)


def as_list(value):
    """把 list / 逗号分隔字符串统一成去空列表。"""
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]
    return []


def parse_command(text, bare=False):
    """取消息里的命令名，不是命令返回空串。

    AstrBot 唤醒时会把唤醒前缀吃掉："/whoami" 传给插件时已经变成 "whoami"。
    所以 bare=True（已唤醒）时，裸命令名也算命令，和框架的匹配口径保持一致。
    """
    raw = str(text or "").strip()
    if not raw:
        return ""
    token = raw.replace("／", "/").split()[0]
    if token.startswith("/"):
        return token.lstrip("/").split("@")[0].lower()
    if bare:
        name = token.split("@")[0].lower()
        if name in KNOWN_COMMANDS:
            return name
    return ""


def identity(umo="", sender_id="", admin_umos=None, admin_ids=None, member_umos=None):
    """判断说话的人是谁。

    返回 (role, reason)，role 取 ADMIN / MEMBER / GUEST。
    openid 优先于会话：openid 是「人」，umo 是「一段对话」。
    """
    admins = as_list(admin_umos)
    ids = as_list(admin_ids)
    members = as_list(member_umos)
    umo = str(umo or "")
    sender_id = str(sender_id or "")

    if not admins and not ids:
        return ADMIN, "未配置主账号，处于开放模式（谁都能用全部命令）"
    if sender_id and sender_id in ids:
        return ADMIN, "openid 命中主账号名单"
    if umo and umo in admins:
        return ADMIN, "会话命中主账号名单"
    if sender_id and sender_id in members:
        return MEMBER, "openid 在成员名单"
    if umo and umo in members:
        return MEMBER, "会话在成员名单"
    return GUEST, "不在任何名单里"


def gate(text, role, allow_self_bind=False, member_allow_all=False, bare=False):
    """决定这条消息要不要放行。

    返回 {"allow": bool, "command": str, "role": str, "reason": str}。
    member_allow_all=True 时，成员和主账号同权（可以聊天、可以用全部命令）。
    """
    command = parse_command(text, bare=bare)
    if role == ADMIN:
        return {"allow": True, "command": command, "role": role, "reason": "主账号，全部放行"}
    if role == MEMBER and member_allow_all:
        return {"allow": True, "command": command, "role": role, "reason": "成员，全部放行"}
    if not command:
        return {"allow": False, "command": "", "role": role, "reason": "不是命令消息，直接丢掉"}
    if command in GUEST_COMMANDS:
        return {"allow": True, "command": command, "role": role, "reason": "受限指令，允许"}
    if command == SELF_BIND_COMMAND:
        if allow_self_bind:
            return {"allow": True, "command": command, "role": role, "reason": "已开启自助绑定"}
        return {"allow": False, "command": command, "role": role, "reason": "未开启自助绑定"}
    return {"allow": False, "command": command, "role": role, "reason": "非主账号，拒绝"}


def matrix(allow_self_bind=False, has_members=True, member_allow_all=False):
    """自检用：几种身份 x 几条命令的放行结果。"""
    roles = [
        ("主账号（会话）", ADMIN),
        ("主账号（openid）", ADMIN),
        ("已绑定同学", MEMBER if has_members else GUEST),
        ("陌生人", GUEST),
    ]
    rows = []
    for label, role in roles:
        cells = []
        for command in MATRIX_COMMANDS:
            decision = gate(command, role, allow_self_bind=allow_self_bind,
                            member_allow_all=member_allow_all)
            cells.append({
                "command": command,
                "allow": decision["allow"],
                "reason": decision["reason"],
            })
        rows.append({"who": label, "role": role, "cells": cells})
    return {"commands": list(MATRIX_COMMANDS), "rows": rows}
