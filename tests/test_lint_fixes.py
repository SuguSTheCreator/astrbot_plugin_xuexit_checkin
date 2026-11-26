"""工业化第 1 轮体检抓出来的真问题，逐条钉住。"""
import http.server
import json
import os
import tempfile
import threading
import unittest

from chaoxing.errors import NetworkError
from chaoxing.service import _retry


class TestRetryNeverRaisesNone(unittest.TestCase):
    """原来 attempts=0 时会 raise None → TypeError，而不是有意义的错误。"""

    def test_zero_attempts_still_runs_once(self):
        calls = []

        def fn():
            calls.append(1)
            return "ok"

        self.assertEqual(_retry(fn, None, attempts=0), "ok")
        self.assertEqual(len(calls), 1)

    def test_negative_attempts_still_runs_once(self):
        self.assertEqual(_retry(lambda: "ok", None, attempts=-5), "ok")

    def test_zero_attempts_network_error_raises_networkerror(self):
        def fn():
            raise NetworkError("boom")

        with self.assertRaises(NetworkError):
            _retry(fn, None, attempts=0)

    def test_retries_then_succeeds(self):
        state = {"n": 0}

        def fn():
            state["n"] += 1
            if state["n"] < 3:
                raise NetworkError("flaky")
            return "ok"

        self.assertEqual(_retry(fn, None, attempts=3), "ok")
        self.assertEqual(state["n"], 3)


class _Echo(http.server.BaseHTTPRequestHandler):
    seen = []

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        _Echo.seen.append(json.loads(self.rfile.read(n).decode("utf-8") or "{}"))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"code":200}')

    def log_message(self, *args):
        pass


class TestCliMultiAccountWebhook(unittest.TestCase):
    """原来只有 CLI 单账号模式发 webhook，多账号模式完全不发。"""

    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.HTTPServer(("127.0.0.1", 0), _Echo)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        _Echo.seen = []
        self.dir = tempfile.mkdtemp()

    def test_multi_account_sends_summary(self):
        from standalone.cli import main

        url = "http://127.0.0.1:%d/hook" % self.port
        accounts = {
            "defaults": {
                "cookie": "_uid=1; uf=bogus",
                "form_id": "123456",
                "enc": "0123456789abcdef0123456789abcdef",
                "fid_enc": "0123456789abcdef",
                "state_fid": "39037",
                "dry_run": True,
                "webhook_url": url,
            },
            "accounts": [{"name": "甲"}, {"name": "乙"}],
        }
        path = os.path.join(self.dir, "accounts.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(accounts, fh, ensure_ascii=False)

        code = main(["--accounts", path, "--state-dir", os.path.join(self.dir, "st"),
                     "--dry-run"])
        self.assertEqual(code, 1)  # 假 cookie，打卡失败
        self.assertEqual(len(_Echo.seen), 1, "多账号模式应该发一条汇总")
        body = _Echo.seen[0]
        self.assertIn("甲", body["content"])
        self.assertIn("乙", body["content"])
        self.assertIn("完成", body["content"])

    def test_no_webhook_url_sends_nothing(self):
        from standalone.cli import main

        accounts = {
            "defaults": {
                "cookie": "_uid=1; uf=bogus", "form_id": "123456",
                "enc": "0123456789abcdef0123456789abcdef",
                "fid_enc": "0123456789abcdef", "state_fid": "39037", "dry_run": True,
            },
            "accounts": [{"name": "甲"}],
        }
        path = os.path.join(self.dir, "a2.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(accounts, fh, ensure_ascii=False)
        main(["--accounts", path, "--state-dir", os.path.join(self.dir, "st2"), "--dry-run"])
        self.assertEqual(_Echo.seen, [])


if __name__ == "__main__":
    unittest.main()
