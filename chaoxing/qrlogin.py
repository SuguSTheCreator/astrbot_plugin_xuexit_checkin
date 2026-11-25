"""超星扫码登录：生成二维码 + 轮询确认状态（与机器人/CLI 解耦）。"""
import re

import requests

LOGIN_PAGE = "/login"
QR_IMAGE = "/createqr"
QR_STATUS = "/getauthstatus/v2"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

STATE_WAITING = "waiting"
STATE_SCANNED = "scanned"
STATE_EXPIRED = "expired"
STATE_CONFIRMED = "confirmed"
STATE_ERROR = "error"

_TYPE_MAP = {
    "3": STATE_WAITING,
    "4": STATE_SCANNED,
    "2": STATE_EXPIRED,
    "6": STATE_EXPIRED,
    "7": STATE_ERROR,
}

_UUID_RE = re.compile(r'value="([0-9a-f]{32})"\s+id="uuid"')
_ENC_RE = re.compile(r'value="([0-9a-f]{32})"\s+id="enc"')


class QrLoginError(Exception):
    """扫码登录失败（页面结构变化 / 网络异常）。"""


def _extract(html, pattern):
    match = pattern.search(html or "")
    return match.group(1) if match else ""


class QrLoginSession:
    """一次扫码登录会话：refresh() 出码，poll() 轮询，confirmed 后取 cookies。"""

    def __init__(self, fid="", base_url="https://passport2.chaoxing.com",
                 refer="http://i.chaoxing.com", session=None, timeout=20.0, proxy=""):
        self.proxy = str(proxy or "").strip()
        self.fid = str(fid or "")
        self.base_url = str(base_url).rstrip("/")
        self.refer = refer
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": UA})
        if self.proxy:
            self.session.proxies.update({"http": self.proxy, "https": self.proxy})
        self.uuid = ""
        self.enc = ""
        self.qr_image = b""
        self.nickname = ""
        self.uid = ""

    def refresh(self):
        params = {"fid": self.fid, "newversion": "true", "refer": self.refer}
        html = self.session.get(
            self.base_url + LOGIN_PAGE, params=params, timeout=self.timeout
        ).text
        self.uuid = _extract(html, _UUID_RE)
        self.enc = _extract(html, _ENC_RE)
        if not self.uuid or not self.enc:
            raise QrLoginError("登录页里没找到 uuid/enc，可能页面结构变了")
        image = self.session.get(
            self.base_url + QR_IMAGE,
            params={"uuid": self.uuid, "fid": "-1"},
            timeout=self.timeout,
        )
        if image.status_code != 200 or not image.content:
            raise QrLoginError("二维码图片下载失败")
        self.qr_image = image.content
        self.nickname = ""
        self.uid = ""
        return self.qr_image

    def poll(self):
        if self.cookies_ready():
            return self._confirmed()
        data = {
            "enc": self.enc,
            "uuid": self.uuid,
            "doubleFactorLogin": "0",
            "forbidotherlogin": "0",
        }
        resp = self.session.post(
            self.base_url + QR_STATUS, data=data, timeout=self.timeout
        )
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        if self.cookies_ready() or payload.get("status"):
            return self._confirmed()
        state = _TYPE_MAP.get(str(payload.get("type")), STATE_WAITING)
        self.nickname = str(payload.get("nickname") or self.nickname)
        self.uid = str(payload.get("uid") or self.uid)
        return {"state": state, "nickname": self.nickname, "uid": self.uid}

    def cookies_ready(self):
        return "_uid" in self.session.cookies.get_dict()

    def cookie_string(self):
        return "; ".join("%s=%s" % (k, v) for k, v in self.session.cookies.get_dict().items())

    def _confirmed(self):
        return {
            "state": STATE_CONFIRMED,
            "nickname": self.nickname,
            "uid": self.uid,
            "cookies": self.session.cookies.get_dict(),
        }