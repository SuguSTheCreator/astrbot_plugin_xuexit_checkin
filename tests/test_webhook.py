import http.server
import json
import threading
import unittest

from adapters.webhook import build_request, send_webhook


class TestBuildRequest(unittest.TestCase):
    """纯函数：各家字段名必须对，否则 HTTP 200 也收不到消息。"""

    def test_serverchan_uses_form_desp(self):
        kw = build_request("https://sctapi.ftqq.com/KEY.send", "标题", "正文")
        self.assertIn("data", kw)
        self.assertEqual(kw["data"], {"title": "标题", "desp": "正文"})

    def test_pushplus_uses_json_content_and_token(self):
        kw = build_request("https://www.pushplus.plus/send?token=abc", "标题", "正文")
        self.assertIn("json", kw)
        self.assertEqual(kw["json"]["token"], "abc")
        self.assertEqual(kw["json"]["content"], "正文")
        self.assertNotIn("desp", kw["json"])

    def test_pushplus_without_token_omits_field(self):
        kw = build_request("https://www.pushplus.plus/send", "t", "x")
        self.assertNotIn("token", kw["json"])
        self.assertEqual(kw["json"]["content"], "x")

    def test_bark_uses_body(self):
        kw = build_request("https://api.day.app/KEY", "标题", "正文")
        self.assertEqual(kw["json"], {"title": "标题", "body": "正文"})

    def test_custom_gets_all_aliases(self):
        kw = build_request("https://example.com/hook", "标题", "正文")
        self.assertEqual(kw["json"], {"title": "标题", "text": "正文", "content": "正文"})

    def test_host_not_substring_of_path(self):
        kw = build_request("https://example.com/pushplus", "t", "x")
        self.assertIn("text", kw["json"])


class _Handler(http.server.BaseHTTPRequestHandler):
    seen = []
    reply = b'{"code":200}'

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode("utf-8", "ignore")
        _Handler.seen.append(raw)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(_Handler.reply)

    def log_message(self, *args):
        pass


class TestSendWebhook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        _Handler.seen = []
        _Handler.reply = b'{"code":200}'

    def url(self):
        return "http://127.0.0.1:%d/hook" % self.port

    def test_empty_url(self):
        self.assertFalse(send_webhook("", "t", "x"))

    def test_success_posts_json(self):
        self.assertTrue(send_webhook(self.url(), "标题", "正文"))
        self.assertEqual(json.loads(_Handler.seen[-1])["content"], "正文")

    def test_body_code_failure_is_not_success(self):
        _Handler.reply = b'{"code":400,"msg":"token invalid"}'
        self.assertFalse(send_webhook(self.url(), "t", "x"))

    def test_body_without_code_is_success(self):
        _Handler.reply = b'{"ok":true}'
        self.assertTrue(send_webhook(self.url(), "t", "x"))

    def test_non_json_body_is_success(self):
        _Handler.reply = b'OK'
        self.assertTrue(send_webhook(self.url(), "t", "x"))

    def test_unreachable_returns_false(self):
        self.assertFalse(send_webhook("http://127.0.0.1:1/nope", "t", "x", timeout=1.0))


if __name__ == "__main__":
    unittest.main()
