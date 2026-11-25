import json
import unittest

from chaoxing.errors import ConfigError
from chaoxing.forms import build_form_data, parse_location

TEMPLATE = {
    "74": {
        "compt": "radiobutton",
        "groupValues": [{"values": [[{"val": "健康"}]], "isShow": True}],
    },
    "75": {
        "compt": "location",
        "groupValues": [{"values": [[{"lat": 0, "lng": 0, "address": ""}]], "isShow": True}],
    },
}


class FormsTest(unittest.TestCase):
    def test_parse_location(self):
        loc = parse_location("31.1,106.6,湖北省武汉市")
        self.assertEqual(loc["lat"], 31.1)
        self.assertEqual(loc["lng"], 106.6)
        self.assertEqual(loc["address"], "湖北省武汉市")

    def test_build_injects_location(self):
        text = build_form_data(json.dumps(TEMPLATE, ensure_ascii=False), "31.1,106.6,武汉市")
        data = json.loads(text)
        value = data["75"]["groupValues"][0]["values"][0][0]
        self.assertEqual(value["lat"], 31.1)
        self.assertEqual(value["address"], "武汉市")

    def test_empty_template_raises(self):
        with self.assertRaises(ConfigError):
            build_form_data("", None)

    def test_bad_json_raises(self):
        with self.assertRaises(ConfigError):
            build_form_data("{bad", None)
