"""配置结构迁移：AstrBot 补默认值，但不搬运改过名的旧键。"""
import unittest

import config_migrate


class TestConfigMigration(unittest.TestCase):
    def setUp(self):
        self._orig = dict(config_migrate.LEGACY_CONFIG_KEYS)

    def tearDown(self):
        config_migrate.LEGACY_CONFIG_KEYS.clear()
        config_migrate.LEGACY_CONFIG_KEYS.update(self._orig)

    def test_stamps_version_on_old_config(self):
        cfg = {"ENABLE": True}
        moved, changed = config_migrate.migrate(cfg)
        self.assertTrue(changed)
        self.assertEqual(moved, [])
        self.assertEqual(cfg["CONFIG_SCHEMA_VERSION"], config_migrate.CONFIG_SCHEMA_VERSION)

    def test_already_current_is_noop(self):
        cfg = {"CONFIG_SCHEMA_VERSION": config_migrate.CONFIG_SCHEMA_VERSION}
        moved, changed = config_migrate.migrate(cfg)
        self.assertFalse(changed)
        self.assertEqual(moved, [])

    def test_legacy_key_value_is_moved(self):
        config_migrate.LEGACY_CONFIG_KEYS["OLD_ENC"] = "FORM_ENC"
        cfg = {"OLD_ENC": "user-value"}
        moved, changed = config_migrate.migrate(cfg)
        self.assertTrue(changed)
        self.assertEqual(cfg["FORM_ENC"], "user-value")
        self.assertEqual(moved, ["OLD_ENC→FORM_ENC"])

    def test_new_key_already_set_is_not_overwritten(self):
        config_migrate.LEGACY_CONFIG_KEYS["OLD_ENC"] = "FORM_ENC"
        cfg = {"OLD_ENC": "old", "FORM_ENC": "new"}
        config_migrate.migrate(cfg)
        self.assertEqual(cfg["FORM_ENC"], "new")

    def test_empty_legacy_value_is_skipped(self):
        config_migrate.LEGACY_CONFIG_KEYS["OLD_ENC"] = "FORM_ENC"
        for empty in ("", None, []):
            cfg = {"OLD_ENC": empty}
            config_migrate.migrate(cfg)
            self.assertNotIn("FORM_ENC", cfg)

    def test_bad_version_value_is_treated_as_zero(self):
        cfg = {"CONFIG_SCHEMA_VERSION": "oops"}
        _, changed = config_migrate.migrate(cfg)
        self.assertTrue(changed)
        self.assertEqual(cfg["CONFIG_SCHEMA_VERSION"], config_migrate.CONFIG_SCHEMA_VERSION)

    def test_missing_version_key_is_treated_as_zero(self):
        cfg = {}
        _, changed = config_migrate.migrate(cfg)
        self.assertTrue(changed)


if __name__ == "__main__":
    unittest.main()
