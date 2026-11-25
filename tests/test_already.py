import unittest

from chaoxing.client import _parse_submit_response
from chaoxing.errors import AlreadySubmitted, SubmitError


class _Resp:
    def __init__(self, text, status=200):
        self.status_code = status
        self.text = text


class TestAlreadySubmitted(unittest.TestCase):
    def test_limit_message_is_not_a_failure(self):
        resp = _Resp('{"success":false,"msg":"每个用户每日只能填写1次，您的提交已达上限哦~"}')
        with self.assertRaises(AlreadySubmitted):
            _parse_submit_response(resp)

    def test_other_error_still_fails(self):
        resp = _Resp('{"success":false,"msg":"参数错误"}')
        with self.assertRaises(SubmitError):
            _parse_submit_response(resp)

    def test_success_still_ok(self):
        resp = _Resp('{"success":true}')
        self.assertTrue(_parse_submit_response(resp))


if __name__ == "__main__":
    unittest.main()
