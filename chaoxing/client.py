"""超星表单 HTTP 客户端。"""
import json
from urllib.parse import parse_qs, urlparse

import requests

from .errors import (
    AlreadySubmitted,
    CheckCodeError,
    CookieExpiredError,
    NetworkError,
    SubmitError,
)

FORM_URL = "/front/web/apps/forms/fore/apply"
SUBMIT_URL = "/data/apps/forms/fore/user/save"
LAST_INFO_URL = "/data/apps/forms/fore/forms/user/last/info"
LOGIN_HINTS = ("passport2", "用户登录", "login?refer")


class ChaoxingClient:
    def __init__(self, config, session=None):
        self.config = config
        self.session = session or requests.Session()
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/json,*/*",
            "Cookie": config.cookie,
            "Referer": config.base_url + "/",
        }

    def _get(self, url, **kwargs):
        try:
            return self.session.get(
                url, headers=self.headers, timeout=self.config.timeout, **kwargs
            )
        except requests.RequestException as exc:
            raise NetworkError("网络请求失败", detail=str(exc))

    def _post(self, url, data):
        headers = dict(self.headers)
        headers["Origin"] = self.config.base_url
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        try:
            return self.session.post(
                url, data=data, headers=headers, timeout=self.config.timeout
            )
        except requests.RequestException as exc:
            raise NetworkError("网络提交失败", detail=str(exc))

    def get_check_code(self):
        params = {"id": self.config.form_id, "enc": self.config.enc}
        if self.config.fid_enc:
            params["fidEnc"] = self.config.fid_enc
        url = self.config.base_url + FORM_URL
        resp = self._get(url, params=params, allow_redirects=False)
        status = getattr(resp, "status_code", 0)
        location = resp.headers.get("Location", "") if getattr(resp, "headers", None) else ""

        if status in (301, 302, 303, 307, 308):
            code = _extract_check_code(location)
            if code:
                return code
            if _looks_like_login(location):
                raise CookieExpiredError(
                    "Cookie 已失效，请重新登录超星后更新 Cookie", detail=location
                )
            raise CheckCodeError("302 跳转里没有 checkCode", detail=location)

        if status == 200:
            text = getattr(resp, "text", "") or ""
            if _looks_like_login(text):
                raise CookieExpiredError("Cookie 已失效，请重新登录超星后更新 Cookie")
            raise CheckCodeError(
                "未发生跳转，可能 Cookie 无效或表单链接已变更", detail="HTTP 200"
            )

        if status in (401, 403):
            raise CookieExpiredError("HTTP " + str(status) + "：Cookie 或权限有问题")

        raise CheckCodeError(
            "获取 checkCode 失败（HTTP " + str(status) + "）",
            detail=(getattr(resp, "text", "") or "")[:300],
        )

    def fetch_last_submission(self):
        """拉取本账号上一次的提交，用于自动同步 uuid / enc / 表单模板。

        返回 dict(uuid, enc, version, form_data, uid)；拿不到时返回 None。
        Cookie 失效会抛 CookieExpiredError，其他情况一律返回 None。
        """
        params = {
            "formId": self.config.form_id,
            "enc": self.config.enc,
            "formAppId": "",
            "cpage": "1",
        }
        resp = self._get(self.config.base_url + LAST_INFO_URL, params=params)
        status = getattr(resp, "status_code", 0)
        if status in (401, 403):
            raise CookieExpiredError("拉取上次提交被拒绝（HTTP " + str(status) + "）")
        text = getattr(resp, "text", "") or ""
        if _looks_like_login(text):
            raise CookieExpiredError("拉取上次提交时被跳转到登录页，Cookie 已失效")
        try:
            payload = json.loads(text)
        except (ValueError, TypeError):
            return None
        if not isinstance(payload, dict) or not payload.get("success"):
            return None
        data = payload.get("data") or {}
        user = data.get("formsUser") if isinstance(data, dict) else None
        if not isinstance(user, dict):
            return None
        return {
            "uuid": user.get("uuid") or "",
            "enc": user.get("enc") or "",
            "version": user.get("version"),
            "form_data": user.get("formIdValueData"),
            "uid": user.get("uid"),
        }

    def submit(self, check_code, form_data_json, overrides=None):
        ov = overrides or {}
        data = {
            "formId": self.config.form_id,
            "version": str(ov.get("version") or "1"),
            "formIdValueData": form_data_json,
            "t": "1",
            "enc": ov.get("enc") or self.config.enc,
            "uuid": ov.get("uuid") or self.config.uuid,
            "checkCode": check_code,
            "submitVersion": self.config.submit_version,
        }
        if self.config.state_fid:
            data["stateFid"] = self.config.state_fid
        extras = self.config.extra_params
        if isinstance(extras, str) and extras.strip():
            try:
                extras = json.loads(extras)
            except ValueError:
                extras = {}
        if isinstance(extras, dict):
            for key, value in extras.items():
                if key not in data and value is not None:
                    data[str(key)] = str(value)
        resp = self._post(self.config.base_url + SUBMIT_URL, data)
        return _parse_submit_response(resp)


def _extract_check_code(location):
    if not location:
        return ""
    query = parse_qs(urlparse(location).query)
    values = query.get("checkCode") or []
    return values[0] if values else ""


def _looks_like_login(text):
    if not text:
        return False
    low = text.lower()
    return any(hint.lower() in low for hint in LOGIN_HINTS)


#: 提交接口的「今天已经交过了」提示语，命中就当作成功，别当失败报错
ALREADY_HINTS = (
    "只能填写1次", "只能填写一次", "已达上限", "已提交过", "已经提交", "已经填写",
)


def _parse_submit_response(resp):
    status = getattr(resp, "status_code", 0)
    text = getattr(resp, "text", "") or ""
    if status in (401, 403):
        raise CookieExpiredError("提交被拒绝（HTTP " + str(status) + "）", detail=text[:300])
    if status >= 500:
        raise NetworkError("服务器错误（HTTP " + str(status) + "）", detail=text[:300])
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        raise SubmitError("提交返回的不是 JSON", detail=text[:300])

    ok = False
    if isinstance(payload, dict):
        for key in ("success", "status", "result", "ok"):
            if isinstance(payload.get(key), bool):
                ok = payload[key]
                break
        if not ok:
            msg = str(payload.get("msg") or payload.get("message") or "")
            if "成功" in msg:
                ok = True
    if not ok:
        msg = payload.get("msg") if isinstance(payload, dict) else None
        msg_text = str(msg or "")
        if any(hint in msg_text for hint in ALREADY_HINTS):
            raise AlreadySubmitted("今天已经提交过（每日限 1 次）", detail=text[:300])
        raise SubmitError("提交失败：" + str(msg_text or "未知原因"), detail=text[:500])
    return payload
