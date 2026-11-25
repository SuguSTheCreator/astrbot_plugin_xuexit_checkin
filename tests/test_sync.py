"""自动同步参数的行为测试。"""
import unittest

from chaoxing.models import CheckinConfig
from chaoxing.service import run_once


class FakeClient:
    def __init__(self, config, fresh=None):
        self.config = config
        self.fresh = fresh
        self.overrides = None
        self.submitted = None

    def get_check_code(self):
        return "code-123"

    def fetch_last_submission(self):
        return self.fresh

    def submit(self, check_code, form_data_json, overrides=None):
        self.overrides = overrides
        self.submitted = form_data_json
        return {"success": True}


def _cfg(**kwargs):
    base = {
        "cookie": "uf=1",
        "form_id": "123456",
        "enc": "abc123",
        "uuid": "cfg-uuid",
        "submit_version": "178",
        "form_template": '{"1": {"compt": "text"}}',
        "dry_run": False,
        "state_path": "/tmp/test-sync-state.json",
    }
    base.update(kwargs)
    return CheckinConfig.from_dict(base)


class SyncTest(unittest.TestCase):
    def test_uses_fresh_template_and_uuid(self):
        fresh = {
            "uuid": "fresh-uuid",
            "enc": "record-enc",
            "version": 1,
            "form_data": {"7": {"compt": "radiobutton"}},
        }
        holder = {}

        def factory(config):
            holder["client"] = FakeClient(config, fresh=fresh)
            return holder["client"]

        result = run_once(_cfg(), force=True, client_factory=factory)
        self.assertTrue(result.ok)
        self.assertEqual(result.stage, "submit_auto")
        self.assertTrue(result.synced)
        client = holder["client"]
        self.assertEqual(client.overrides.get("uuid"), "fresh-uuid")
        self.assertNotIn("enc", client.overrides or {})
        self.assertIn("radiobutton", client.submitted)

    def test_falls_back_to_config_when_no_history(self):
        holder = {}

        def factory(config):
            holder["client"] = FakeClient(config)
            return holder["client"]

        result = run_once(_cfg(), force=True, client_factory=factory)
        self.assertTrue(result.ok)
        self.assertEqual(result.stage, "submit")
        self.assertFalse(result.synced)
        self.assertIn("text", holder["client"].submitted)

    def test_auto_sync_can_be_disabled(self):
        fresh = {"uuid": "fresh-uuid", "form_data": {"7": {}}}
        holder = {}

        def factory(config):
            holder["client"] = FakeClient(config, fresh=fresh)
            return holder["client"]

        result = run_once(_cfg(auto_sync=False), force=True, client_factory=factory)
        self.assertEqual(result.stage, "submit")
        self.assertIsNone(holder["client"].overrides)


if __name__ == "__main__":
    unittest.main()
