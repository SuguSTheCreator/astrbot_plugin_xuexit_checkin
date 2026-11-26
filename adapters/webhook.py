"""通用 Webhook 推送：Server酱 / PushPlus / Bark / 自定义 URL。

各家字段名不一样，发错了会「HTTP 200 但收不到消息」，所以按域名分别构造：
  Server酱  ftqq.com        表单 title + desp
  PushPlus  pushplus.plus   JSON token + title + content（content 必填）
  Bark      day.app         JSON title + body
  其他                      JSON title + text + content

构造与发送分开，方便测试：build_request() 是纯函数，不碰网络。
"""
from urllib.parse import parse_qs, urlparse

import requests


def build_request(url, title, text):
    """返回 requests.post 的关键字参数（data= 或 json=）。"""
    host = urlparse(url).netloc.lower()
    if "ftqq.com" in host:
        return {"data": {"title": title, "desp": text}}
    if "pushplus" in host:
        token = (parse_qs(urlparse(url).query).get("token") or [""])[0]
        payload = {"title": title, "content": text, "template": "txt"}
        if token:
            payload["token"] = token
        return {"json": payload}
    if "day.app" in host:
        return {"json": {"title": title, "body": text}}
    return {"json": {"title": title, "text": text, "content": text}}


def _body_ok(resp):
    """有些服务失败也返回 HTTP 200，真正的结论在 body 的 code 里。"""
    try:
        data = resp.json()
    except ValueError:
        return True
    if not isinstance(data, dict):
        return True
    for key in ("code", "errno", "status"):
        if key in data:
            value = data[key]
            if isinstance(value, bool):
                return value
            try:
                return int(value) in (0, 200)
            except (TypeError, ValueError):
                return str(value).lower() in ("0", "200", "ok", "success")
    return True


def send_webhook(url, title, text, timeout=10.0):
    if not url:
        return False
    try:
        resp = requests.post(url, timeout=timeout, **build_request(url, title, text))
        resp.raise_for_status()
        return _body_ok(resp)
    except (requests.RequestException, ValueError):
        return False
