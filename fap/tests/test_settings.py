"""设置声明与保存：框架项写顶层、插件项写 plugins.<id>、密钥打码。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from framework.app import FapApp
from framework.settings import SettingSpec, SettingsRegistry

ROOT = Path(__file__).resolve().parents[1]


class SettingsRegistryTest(unittest.TestCase):
    def test_coerce_types(self) -> None:
        self.assertEqual(SettingSpec("a", "a", "int", 0).coerce("42"), 42)
        self.assertEqual(SettingSpec("a", "a", "int", 7).coerce("坏值"), 7)
        self.assertEqual(SettingSpec("a", "a", "float", 0.0).coerce("1.5"), 1.5)
        self.assertTrue(SettingSpec("a", "a", "bool", False).coerce("true"))
        self.assertFalse(SettingSpec("a", "a", "bool", True).coerce("0"))
        self.assertEqual(SettingSpec("a", "a", "list", []).coerce("x, y，z"), ["x", "y", "z"])
        self.assertEqual(SettingSpec("a", "a", "text", "").coerce(123), "123")

    def test_register_and_unregister_owner(self) -> None:
        registry = SettingsRegistry()
        registry.register([SettingSpec("k", "K")], owner="p1")
        self.assertEqual([spec.key for spec in registry.specs("p1")], ["k"])
        self.assertIn("p1", registry.owners())
        self.assertEqual(registry.unregister_owner("p1"), 1)
        self.assertEqual(registry.specs("p1"), [])


class SettingsSaveTest(unittest.TestCase):
    def test_framework_and_plugin_save(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            app = FapApp(root=Path(folder), log_to_file=False)
            app.plugins.plugins_dir = ROOT / "plugins"

            import asyncio

            asyncio.run(app.start(connect=False))

            specs = {spec.key: spec for spec in app.settings.specs("")}
            self.assertIn("appid", specs)
            self.assertIn("appsecret", specs)
            self.assertEqual(specs["appsecret"].kind, "secret")

            app.save_settings({"appid": "123456", "appsecret": "s3cret", "max_chars": "900",
                               "group_enabled": "false"}, owner="")
            saved = json.loads((Path(folder) / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["appid"], "123456")
            self.assertEqual(saved["appsecret"], "s3cret")
            self.assertEqual(saved["max_chars"], 900)
            self.assertIs(saved["group_enabled"], False)

            # 插件设置写进 plugins.<id>
            plugin_specs = {spec.key for spec in app.settings.specs("pet_game")}
            self.assertIn("feed_cooldown_s", plugin_specs)
            app.save_settings({"feed_cooldown_s": "45"}, owner="pet_game")
            saved = json.loads((Path(folder) / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["plugins"]["pet_game"]["feed_cooldown_s"], 45)

            # 掩码：snapshot 里不出现明文密钥
            masked = app.config.snapshot()
            self.assertEqual(masked["appsecret"], "***")

            asyncio.run(app.stop())


if __name__ == "__main__":
    unittest.main()
