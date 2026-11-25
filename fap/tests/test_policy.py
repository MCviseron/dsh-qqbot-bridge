"""框架策略：主人落盘、静默时段、限流、入站去重、Markdown 判定。"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from framework.app import FapApp
from framework.bot import QQBot, looks_like_markdown

ROOT = Path(__file__).resolve().parents[1]


class PermissionTest(unittest.TestCase):
    def test_registry_defaults_to_deny(self) -> None:
        from framework.permissions import PermissionRegistry
        from framework.types import Message, Sender, Target

        registry = PermissionRegistry()
        message = Message(
            id="M1", kind="group", conv_key="group:A",
            sender=Sender(openid="U1"), text="/x",
            target=Target(kind="group", openid="A", conv_key="group:A"),
        )
        self.assertTrue(registry.has(message, ""))            # 不要求角色
        self.assertFalse(registry.has(message, "owner"))      # 没人声明就拒绝

    def test_plugin_registered_role(self) -> None:
        from framework.permissions import PermissionRegistry
        from framework.types import Message, Sender, Target

        registry = PermissionRegistry()
        registry.register(lambda message, role: role == "owner" and message.sender.openid == "U1", plugin="p")
        message = Message(
            id="M1", kind="group", conv_key="group:A",
            sender=Sender(openid="U1"), text="/x",
            target=Target(kind="group", openid="A", conv_key="group:A"),
        )
        self.assertTrue(registry.has(message, "owner"))
        self.assertFalse(registry.has(message, "admin"))
        self.assertEqual(registry.unregister_plugin("p"), 1)
        self.assertFalse(registry.has(message, "owner"))


class OwnerGuardPluginTest(unittest.TestCase):
    def test_claim_persists_and_grants_role(self) -> None:
        import asyncio
        from framework.types import Message, Sender, Target

        def boot(folder: str):
            app = FapApp(root=Path(folder), log_to_file=False)
            app.plugins.plugins_dir = ROOT / "plugins"
            asyncio.run(app.start(connect=False))
            return app

        def msg(openid: str) -> Message:
            return Message(
                id="M-" + openid, kind="c2c", conv_key="c2c:" + openid,
                sender=Sender(openid=openid, nickname="测试"), text="/认领",
                target=Target(kind="c2c", openid=openid, conv_key="c2c:" + openid),
            )

        with tempfile.TemporaryDirectory() as folder:
            app = boot(folder)
            plugin = app.plugins.loaded["owner_guard"]
            self.assertFalse(plugin.is_owner("USER-A"))
            asyncio.run(app.on_message(msg("USER-A")))
            self.assertTrue(plugin.is_owner("USER-A"))
            self.assertTrue(app.permissions.has(msg("USER-A"), "owner"))
            self.assertFalse(app.permissions.has(msg("USER-B"), "owner"))
            asyncio.run(app.stop())

            fresh = boot(folder)
            self.assertTrue(fresh.plugins.loaded["owner_guard"].is_owner("USER-A"))
            asyncio.run(fresh.stop())


class PolicyTest(unittest.TestCase):
    def test_quiet_hours_parse(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            app = FapApp(root=Path(folder), log_to_file=False)
            app.config.update({"quiet_hours": "23:30-07:00"})
            self.assertIn(app.in_quiet_hours(), (True, False))   # 只校验解析不炸
            app.config.update({"quiet_hours": "00:00-00:00"})
            self.assertFalse(app.in_quiet_hours())
            app.config.update({"quiet_hours": "坏数据"})
            self.assertFalse(app.in_quiet_hours())

    def test_rate_limit(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            app = FapApp(root=Path(folder), log_to_file=False)
            app.config.update({"rate_limit_per_hour": 2})
            self.assertFalse(app._rate_limited("group:A"))
            self.assertFalse(app._rate_limited("group:A"))
            self.assertTrue(app._rate_limited("group:A"))
            self.assertFalse(app._rate_limited("group:B"))       # 会话之间独立

    def test_dedup(self) -> None:
        bot = QQBot(app=None)
        self.assertFalse(bot._is_duplicate("M1"))
        self.assertTrue(bot._is_duplicate("M1"))
        self.assertFalse(bot._is_duplicate("M2"))
        bot._seen["OLD"] = time.time() - 1000
        self.assertFalse(bot._is_duplicate("OLD"))               # 过期条目被清理后放行

    def test_markdown_detection(self) -> None:
        self.assertTrue(looks_like_markdown("## 标题"))
        self.assertTrue(looks_like_markdown("- 一\n- 二"))
        self.assertTrue(looks_like_markdown("| a | b |"))
        self.assertTrue(looks_like_markdown("**粗体**"))
        self.assertFalse(looks_like_markdown("普通一句话"))


if __name__ == "__main__":
    unittest.main()
