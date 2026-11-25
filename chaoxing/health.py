"""失败原因分类与健康诊断：只读，不提交。

设计：异常类型给出粗分类（stage），再让关键字规则细化——
因为同一个 SubmitError 里，超星会返回各种各样的 msg：
  「每个用户每日只能填写1次」→ 其实成功了
  「表单不存在」            → 该换链接
  「请重新登录」            → 该重扫
只按 stage 分类会把它们混成一坨。
"""
from .client import ChaoxingClient
from .errors import (
    ChaoxingError,
    CheckCodeError,
    ConfigError,
    CookieExpiredError,
    NetworkError,
)

STATUS_OK = "ok"

#: 异常 stage -> 粗分类
STAGE_STATUS = {
    "cookie": "cookie",
    "checkCode": "form",
    "form": "form",
    "config": "config",
    "network": "network",
    "submit": "submit",
    "already": "already",
}

#: 关键字规则：按顺序匹配，先命中先用（放在前面的是更确定的判断）
KEYWORD_RULES = (
    ("already", ("只能填写1次", "只能填写一次", "已达上限", "已经提交", "已提交过", "已经填写")),
    ("form", ("表单不存在", "表单信息不存在", "表单已关闭", "已结束", "未开始", "表单已删除")),
    ("cookie", ("请重新登录", "登录已失效", "未登录", "用户未登录", "cookie", "401", "403")),
    ("config", ("参数错误", "缺少", "uuid", "submitversion", "格式不正确", "参数不合法")),
    ("network", ("超时", "timeout", "连接失败", "网络异常", "502", "503")),
    ("limit", ("频繁", "操作过快", "稍后再试", "次数过多")),
)

#: 状态 -> 建议动作（同时用于打卡失败通知和面板体检）
ACTIONS = {
    "cookie": "让本人重新扫码；扫不了先看登录助手是不是没开",
    "form": "学校可能换了表单：从 App 复制新链接，粘到面板「表单链接」",
    "config": "参数不完整或还是占位值，去面板补全",
    "network": "网络不通，稍后自动重试；持续失败检查服务器网络",
    "limit": "被限频了，把打卡时间窗口拉长，或减少手动触发",
    "submit": "提交被拒但原因不明：看面板「操作留痕」里的原文",
    "already": "不用处理，今天已经提交过",
    "unknown": "看服务器日志里的 traceback",
    "ok": "",
}

#: 状态 -> 通知标签
LABELS = {
    "cookie": "NEED_RELOGIN",
    "form": "FORM_CHANGED",
    "config": "CONFIG",
    "network": "NETWORK",
    "limit": "RATE_LIMIT",
    "submit": "FAIL",
    "unknown": "FAIL",
    "already": "ALREADY",
}


def classify(stage="", message=""):
    """把一次失败翻译成 (status, label, action)。status 为 ok 表示不算失败。"""
    status = STAGE_STATUS.get(str(stage or ""), "")
    text = str(message or "").lower()
    # 只有粗分类不明确时，才让关键字细化
    if text and status in ("", "submit", "unknown"):
        for name, keywords in KEYWORD_RULES:
            if any(k.lower() in text for k in keywords):
                status = name
                break
    status = status or "unknown"
    return status, LABELS.get(status, "FAIL"), ACTIONS.get(status, "")


def advice(stage="", message=""):
    """兼容旧调用：返回 (label, action)。"""
    status, label, action = classify(stage, message)
    return label, action


def _result(status, message, detail=""):
    return {
        "status": status,
        "label": LABELS.get(status, ""),
        "message": message,
        "action": ACTIONS.get(status, ""),
        "detail": str(detail or "")[:200],
    }


def diagnose(config, client_factory=None):
    """只读检查：能不能拿到 checkCode。不提交、不写状态文件。"""
    factory = client_factory or ChaoxingClient
    try:
        client = factory(config)
        code = client.get_check_code()
    except CookieExpiredError as exc:
        return _result("cookie", "Cookie 已失效", exc.detail)
    except CheckCodeError as exc:
        return _result("form", "表单页拿不到 checkCode（可能已换表或关闭）", exc.detail)
    except ConfigError as exc:
        return _result("config", exc.message, exc.detail)
    except NetworkError as exc:
        return _result("network", exc.message, exc.detail)
    except ChaoxingError as exc:
        status, _label, _action = classify(exc.stage, exc.message)
        return _result(status, exc.message, exc.detail)
    except Exception as exc:
        return _result("unknown", "检查失败：" + str(exc), repr(exc))
    return _result("ok", "表单可达，Cookie 有效（checkCode " + str(code)[:8] + "…）")
