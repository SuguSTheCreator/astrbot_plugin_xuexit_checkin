import os
import tempfile
import unittest

from chaoxing.errors import CookieExpiredError
from chaoxing.models import CheckinConfig
from chaoxing.service import run_once


class FakeClient:
    def __init__(self, config):
        self.config = config

    def get_check_code(self):
        return "abc"

    def fetch_last_submission(self):
        return None

    def submit(self, code, form_json, overrides=None):
        return {"success": True}


class BadClient(FakeClient):
    def get_check_code(self):
        raise CookieExpiredError("cookie 失效")


class FallbackClient(FakeClient):
    def __init__(self, config):
        FakeClient.__init__(self, config)
        self.submit_calls = 0

    def submit(self, code, form_json, overrides=None):
        self.submit_calls += 1
        if form_json != "encrypted-blob":
            from chaoxing.errors import SubmitError

            raise SubmitError("明文提交失败")
        return {"success": True}


class ServiceTest(unittest.TestCase):
    def test_dry_run_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = CheckinConfig(
                cookie="c", form_id="1", enc="e", dry_run=True,
                state_path=os.path.join(tmp, "state.json"),
            )
            result = run_once(cfg, client_factory=FakeClient)
            self.assertTrue(result.ok)
            self.assertTrue(result.dry_run)

    def test_fallback_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = CheckinConfig(
                cookie="c", form_id="1", enc="e", dry_run=False,
                uuid="u", submit_version="v",
                form_template={}, fallback_form_data="encrypted-blob",
                state_path=os.path.join(tmp, "state.json"),
            )
            result = run_once(cfg, client_factory=FallbackClient, force=True)
            self.assertTrue(result.ok)
            self.assertEqual(result.stage, "submit_fallback")

    def test_cookie_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = CheckinConfig(
                cookie="c", form_id="1", enc="e", dry_run=True,
                state_path=os.path.join(tmp, "state.json"),
            )
            result = run_once(cfg, client_factory=BadClient)
            self.assertFalse(result.ok)
            self.assertEqual(result.stage, "cookie")