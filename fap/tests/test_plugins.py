"""插件管理器 + 两个内置插件的装配检查（不需要网络/SDK）。"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from framework.app import FapApp
from framework.plugin import PluginManager


ROOT = Path(__file__).resolve().parents[1]


class PluginManagerTest(unittest.TestCase):
    def test_discover_builtin_plugins(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            app = FapApp(root=Path(folder), log_to_file=False)
            manager = PluginManager(app, ROOT / "plugins")
            found = manager.discover()
            self.assertIn("dsh_bridge", found)
            self.assertIn("pet_game", found)
            self.assertEqual(found["pet_game"].version, "1.0.0")

    def test_load_all_registers_commands_and_cleans_up(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            app = FapApp(root=Path(folder), log_to_file=False)
            app.plugins.plugins_dir = ROOT / "plugins"

            async def scenario():
                loaded = await app.plugins.load_all()
                names = {command.name for command in app.commands.unique()}
                self.assertIn("dsh", names)
                self.assertIn("领养", names)
                # dsh_bridge 必须把旧机器人的命令也登记进来（不漏）
                bridge_commands = {c.name for c in app.commands.unique() if c.plugin == "dsh_bridge"}
                for expected in ("状态", "日志", "面板", "分组", "截图", "撤回", "消息池", "绑定"):
                    self.assertIn(expected, bridge_commands)
                self.assertGreaterEqual(len(bridge_commands), 16)
                await app.plugins.unload_all()
                return loaded, {command.name for command in app.commands.unique()}

            loaded, remaining = asyncio.run(scenario())
            self.assertIn("pet_game", loaded)
            self.assertIn("dsh_bridge", loaded)
            # 卸载后插件的命令必须全部摘除（框架核心命令不算）
            self.assertFalse(any(name in remaining for name in ("dsh", "领养", "喂食")))


class PetGameLogicTest(unittest.TestCase):
    def test_level_formula(self) -> None:
        from importlib import util as importlib_util

        spec = importlib_util.spec_from_file_location(
            "pet_plugin_for_test", ROOT / "plugins" / "pet_game" / "plugin.py"
        )
        module = importlib_util.module_from_spec(spec)
        spec.loader.exec_module(module)
        plugin = module.PetGamePlugin()
        self.assertEqual(plugin.level_of(0), 1)
        self.assertEqual(plugin.level_of(49), 1)
        self.assertEqual(plugin.level_of(50), 2)
        self.assertEqual(plugin.level_of(260), 6)

        pet = plugin.new_pet("小肥鱼", "测试")
        self.assertEqual(pet["level"], 1)
        pet["exp"] = 120
        self.assertTrue(plugin.level_up(pet))
        self.assertEqual(pet["level"], 3)
        self.assertFalse(plugin.level_up(pet))


if __name__ == "__main__":
    unittest.main()
