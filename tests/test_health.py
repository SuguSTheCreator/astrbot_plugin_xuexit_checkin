import unittest

from chaoxing.health import classify


class TestClassify(unittest.TestCase):
    def test_already_is_not_failure(self):
        for msg in ("每个用户每日只能填写1次", "您的提交已达上限哦~", "已经提交过了"):
            status, _label, _action = classify("submit", msg)
            self.assertEqual(status, "already", msg)

    def test_form_changed(self):
        for msg in ("表单不存在", "表单已关闭", "该表单已结束"):
            self.assertEqual(classify("submit", msg)[0], "form", msg)

    def test_cookie(self):
        self.assertEqual(classify("cookie", "HTTP 401")[0], "cookie")
        self.assertEqual(classify("submit", "请重新登录")[0], "cookie")

    def test_config(self):
        self.assertEqual(classify("submit", "参数错误")[0], "config")

    def test_network(self):
        self.assertEqual(classify("network", "")[0], "network")
        self.assertEqual(classify("submit", "请求超时")[0], "network")

    def test_limit(self):
        self.assertEqual(classify("submit", "操作过于频繁")[0], "limit")

    def test_stage_wins_when_message_generic(self):
        self.assertEqual(classify("checkCode", "unknown")[0], "form")

    def test_unknown(self):
        self.assertEqual(classify("", "")[0], "unknown")
        self.assertEqual(classify("submit", "今天天气不错")[0], "submit")

    def test_labels(self):
        self.assertEqual(classify("cookie")[1], "NEED_RELOGIN")
        self.assertEqual(classify("checkCode")[1], "FORM_CHANGED")

    def test_action_present(self):
        for stage in ("cookie", "checkCode", "config", "network", "limit", "submit", "unknown"):
            self.assertTrue(classify(stage)[2], stage)


if __name__ == "__main__":
    unittest.main()
