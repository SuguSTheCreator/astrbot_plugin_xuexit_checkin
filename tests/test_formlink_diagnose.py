"""formlink 与 diagnose：原来覆盖率 0% 和 49%，这两块都是用户直接碰到的路径。"""
import unittest

from chaoxing.errors import (
    CheckCodeError,
    ConfigError,
    CookieExpiredError,
    NetworkError,
    SubmitError,
)
from chaoxing.formlink import parse_form_url
from chaoxing.health import classify, diagnose

DETAIL = ("https://office.chaoxing.com/apps/forms/mobile/detail.html"
          "?formId=123456&applyenc=PAGEENC&enc=RECORDENC&state=39037&fidEnc=FIDENC")


class TestParseFormUrl(unittest.TestCase):
    def test_applyenc_wins_over_record_enc(self):
        found, warns = parse_form_url(DETAIL)
        self.assertEqual(found["form_id"], "123456")
        self.assertEqual(found["enc"], "PAGEENC", "详情页必须取 applyenc，不能取记录 enc")
        self.assertEqual(found["fid_enc"], "FIDENC")
        self.assertEqual(found["state_fid"], "39037")
        self.assertEqual(warns, [])

    def test_apply_page_uses_enc(self):
        url = ("https://office.chaoxing.com/front/web/apps/forms/fore/apply"
               "?id=123456&enc=PAGEENC&fidEnc=FIDENC&stateFid=39037")
        found, warns = parse_form_url(url)
        self.assertEqual(found["form_id"], "123456")
        self.assertEqual(found["enc"], "PAGEENC")
        self.assertEqual(found["state_fid"], "39037")
        self.assertEqual(warns, [])

    def test_case_insensitive_keys(self):
        found, _ = parse_form_url("https://x/y?FORMID=1&APPLYENC=E&FIDENC=F&STATE=2")
        self.assertEqual(found["form_id"], "1")
        self.assertEqual(found["enc"], "E")

    def test_missing_fields_are_empty_strings(self):
        found, _ = parse_form_url("https://x/y?formId=1")
        self.assertEqual(found["form_id"], "1")
        self.assertEqual(found["enc"], "")
        self.assertEqual(found["fid_enc"], "")
        self.assertEqual(found["state_fid"], "")

    def test_blank_values_are_ignored(self):
        found, _ = parse_form_url("https://x/y?applyenc=&enc=FALLBACK&formId=1")
        self.assertEqual(found["enc"], "FALLBACK")

    def test_detail_without_applyenc_warns(self):
        _, warns = parse_form_url("https://x/detail.html?formId=1&enc=RECORD")
        self.assertTrue(any("applyenc" in w for w in warns))

    def test_login_page_warns(self):
        _, warns = parse_form_url("https://passport2.chaoxing.com/login?refer=x")
        self.assertTrue(any("登录页" in w for w in warns))

    def test_empty_and_none_input(self):
        for value in ("", None, "   "):
            found, warns = parse_form_url(value)
            self.assertEqual(set(found), {"form_id", "enc", "fid_enc", "state_fid"})
            self.assertTrue(all(v == "" for v in found.values()))
            self.assertEqual(warns, [])

    def test_values_are_stripped(self):
        found, _ = parse_form_url("https://x/y?formId=%20123%20&applyenc=%20E%20")
        self.assertEqual(found["form_id"], "123")
        self.assertEqual(found["enc"], "E")


class _Client:
    def __init__(self, behavior):
        self.behavior = behavior

    def get_check_code(self):
        if isinstance(self.behavior, Exception):
            raise self.behavior
        return self.behavior


class TestDiagnose(unittest.TestCase):
    def _run(self, behavior):
        return diagnose(None, client_factory=lambda cfg: _Client(behavior))

    def test_ok(self):
        r = self._run("abcdefgh12345")
        self.assertEqual(r["status"], "ok")
        self.assertIn("abcdefgh", r["message"])

    def test_cookie_expired(self):
        r = self._run(CookieExpiredError("过期", detail="d"))
        self.assertEqual(r["status"], "cookie")
        self.assertEqual(r["label"], "NEED_RELOGIN")
        self.assertTrue(r["action"])

    def test_check_code_error_maps_to_form(self):
        r = self._run(CheckCodeError("拿不到", detail="d"))
        self.assertEqual(r["status"], "form")

    def test_config_error(self):
        r = self._run(ConfigError("缺参数", detail="d"))
        self.assertEqual(r["status"], "config")

    def test_network_error(self):
        r = self._run(NetworkError("超时", detail="d"))
        self.assertEqual(r["status"], "network")

    def test_submit_error_goes_through_classify(self):
        r = self._run(SubmitError("每个用户每日只能填写1次"))
        self.assertEqual(r["status"], "already")
        self.assertEqual(r["label"], "ALREADY")

    def test_unexpected_exception_is_unknown(self):
        r = self._run(RuntimeError("boom"))
        self.assertEqual(r["status"], "unknown")
        self.assertIn("boom", r["message"])

    def test_detail_is_truncated(self):
        r = self._run(CookieExpiredError("x", detail="y" * 500))
        self.assertLessEqual(len(r["detail"]), 200)


class TestClassifyEdges(unittest.TestCase):
    def test_stage_wins_when_specific(self):
        status, _, _ = classify("cookie", "表单不存在")
        self.assertEqual(status, "cookie")

    def test_keyword_refines_generic_stage(self):
        status, _, _ = classify("submit", "表单不存在")
        self.assertEqual(status, "form")

    def test_empty_everything_is_unknown(self):
        status, label, _ = classify("", "")
        self.assertEqual(status, "unknown")
        self.assertEqual(label, "FAIL")

    def test_every_status_has_label_and_action(self):
        for stage in ("cookie", "form", "config", "network", "submit", "already", ""):
            status, label, action = classify(stage, "")
            self.assertTrue(label)
            if status != "ok":
                self.assertTrue(action, "%s 应该带下一步建议" % status)


if __name__ == "__main__":
    unittest.main()
