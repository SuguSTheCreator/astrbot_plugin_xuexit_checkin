import unittest

from chaoxing.client import ChaoxingClient
from chaoxing.errors import CookieExpiredError, SubmitError
from chaoxing.models import CheckinConfig


class FakeResp:
    def __init__(self, status_code=200, headers=None, text=""):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text


class FakeSession:
    def __init__(self, get_resp=None, post_resp=None):
        self.get_resp = get_resp
        self.post_resp = post_resp
        self.last_post = None

    def get(self, url, **kwargs):
        return self.get_resp

    def post(self, url, **kwargs):
        self.last_post = (url, kwargs)
        return self.post_resp


def make_config(**overrides):
    base = {
        "cookie": "c=1",
        "form_id": "123456",
        "enc": "enc",
        "fid_enc": "fid",
        "state_fid": "39037",
        "uuid": "u",
        "submit_version": "v",
        "dry_run": False,
    }
    base.update(overrides)
    return CheckinConfig(**base)


class ClientTest(unittest.TestCase):
    def test_get_check_code_from_redirect(self):
        session = FakeSession(
            get_resp=FakeResp(
                302,
                {"Location": "https://office.chaoxing.com/x?checkCode=abc123&y=1"},
            )
        )
        client = ChaoxingClient(make_config(), session=session)
        self.assertEqual(client.get_check_code(), "abc123")

    def test_get_check_code_login_redirect(self):
        session = FakeSession(
            get_resp=FakeResp(
                302, {"Location": "https://passport2.chaoxing.com/login?refer=x"}
            )
        )
        client = ChaoxingClient(make_config(), session=session)
        with self.assertRaises(CookieExpiredError):
            client.get_check_code()

    def test_submit_success(self):
        session = FakeSession(post_resp=FakeResp(200, text='{"success": true, "msg": "ok"}'))
        client = ChaoxingClient(make_config(), session=session)
        payload = client.submit("code", "{}")
        self.assertTrue(payload["success"])
        self.assertIn("formIdValueData", session.last_post[1]["data"])

    def test_submit_failure(self):
        session = FakeSession(
            post_resp=FakeResp(200, text='{"success": false, "msg": "表单已提交"}')
        )
        client = ChaoxingClient(make_config(), session=session)
        with self.assertRaises(SubmitError):
            client.submit("code", "{}")

    def test_submit_non_json(self):
        session = FakeSession(post_resp=FakeResp(200, text="<html>login</html>"))
        client = ChaoxingClient(make_config(), session=session)
        with self.assertRaises(SubmitError):
            client.submit("code", "{}")
