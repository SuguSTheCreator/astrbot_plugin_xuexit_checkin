"""CLI 准备配置的两条命令：原来只有面板能解析链接和扫码。"""
import json
import os
import tempfile
import unittest

from standalone.cli import _merge_config, main


class TestParseUrlCommand(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.out = os.path.join(self.dir, "config.json")

    def test_full_link_writes_all_four(self):
        url = ("https://office.chaoxing.com/apps/forms/mobile/detail.html"
               "?formId=123456&applyenc=PAGEENC&enc=RECORD&state=39037&fidEnc=FIDENC")
        self.assertEqual(main(["--parse-url", url, "--out", self.out]), 0)
        with open(self.out, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["enc"], "PAGEENC")
        self.assertEqual(data["form_id"], "123456")
        self.assertEqual(data["state_fid"], "39037")
        self.assertEqual(data["fid_enc"], "FIDENC")

    def test_incomplete_link_returns_one(self):
        self.assertEqual(main(["--parse-url", "https://x/y?formId=1"]), 1)

    def test_merge_keeps_existing_fields(self):
        with open(self.out, "w", encoding="utf-8") as fh:
            json.dump({"cookie": "keep-me", "location": "30,114,门口"}, fh)
        url = "https://x/apply?formId=9&enc=E&fidEnc=F&stateFid=8"
        self.assertEqual(main(["--parse-url", url, "--out", self.out]), 0)
        with open(self.out, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["cookie"], "keep-me")
        self.assertEqual(data["location"], "30,114,门口")
        self.assertEqual(data["form_id"], "9")

    def test_merge_skips_empty_values(self):
        with open(self.out, "w", encoding="utf-8") as fh:
            json.dump({"enc": "OLD"}, fh)
        _merge_config(self.out, {"enc": "", "form_id": "7"})
        with open(self.out, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["enc"], "OLD")
        self.assertEqual(data["form_id"], "7")

    def test_merge_survives_corrupt_existing_file(self):
        with open(self.out, "w", encoding="utf-8") as fh:
            fh.write("{ trunc")
        _merge_config(self.out, {"form_id": "7"})
        with open(self.out, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["form_id"], "7")

    def test_no_args_returns_two(self):
        self.assertEqual(main([]), 2)


if __name__ == "__main__":
    unittest.main()
