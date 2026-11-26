
import pytest

from chaoxing.qrlogin import (
    STATE_CONFIRMED,
    STATE_EXPIRED,
    STATE_SCANNED,
    STATE_WAITING,
    QrLoginError,
    QrLoginSession,
)

PAGE = '<input type="hidden" value="%s" id="uuid"/><input type="hidden" value="%s" id="enc"/>'


class FakeResponse:
    def __init__(self, text="", content=b"", payload=None, status=200):
        self.text = text
        self.content = content
        self._payload = payload
        self.status_code = status

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    def __init__(self, html, qr=b"PNG", polls=None):
        self.headers = {}
        self.html = html
        self.qr = qr
        self.polls = list(polls or [])
        self.cookies = FakeCookies()
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(("GET", url, params))
        if url.endswith("/createqr"):
            return FakeResponse(content=self.qr)
        return FakeResponse(text=self.html)

    def post(self, url, data=None, timeout=None, **kw):
        self.calls.append(("POST", url, data))
        payload = self.polls.pop(0) if self.polls else {"type": "3", "status": False}
        return FakeResponse(payload=payload)


class FakeCookies:
    def __init__(self):
        self.data = {}

    def get_dict(self):
        return dict(self.data)


def make_session(polls=None, cookies=None):
    fake = FakeSession(PAGE % ("a" * 32, "b" * 32), polls=polls)
    if cookies:
        fake.cookies.data.update(cookies)
    return QrLoginSession(fid="39037", session=fake), fake


def test_refresh_extracts_uuid_and_image():
    session, fake = make_session()
    image = session.refresh()
    assert image == b"PNG"
    assert session.uuid == "a" * 32
    assert session.enc == "b" * 32
    assert fake.calls[0][2]["fid"] == "39037"


def test_refresh_raises_when_page_changed():
    fake = FakeSession("<html>no qr</html>")
    with pytest.raises(QrLoginError):
        QrLoginSession(fid="39037", session=fake).refresh()


def test_poll_waiting_then_scanned():
    session, _ = make_session(
        polls=[{"type": "3", "status": False}, {"type": "4", "status": False, "nickname": "张三", "uid": "292"}]
    )
    session.refresh()
    assert session.poll()["state"] == STATE_WAITING
    result = session.poll()
    assert result["state"] == STATE_SCANNED
    assert result["nickname"] == "张三"


def test_poll_expired():
    session, _ = make_session(polls=[{"type": "2", "status": False}])
    session.refresh()
    assert session.poll()["state"] == STATE_EXPIRED


def test_poll_confirmed_by_status():
    session, fake = make_session(polls=[{"type": "3", "status": True}])
    session.refresh()
    fake.cookies.data["_uid"] = "100000001"
    result = session.poll()
    assert result["state"] == STATE_CONFIRMED
    assert "_uid" in result["cookies"]


def test_poll_confirmed_by_cookie_before_request():
    session, fake = make_session()
    session.refresh()
    fake.cookies.data["_uid"] = "1"
    result = session.poll()
    assert result["state"] == STATE_CONFIRMED


def test_cookie_string_format():
    session, fake = make_session()
    session.refresh()
    fake.cookies.data.update({"_uid": "1", "uf": "abc"})
    assert session.cookie_string() == "_uid=1; uf=abc"
