"""GUI 控制台：快照函数与插件操作（不需要起 HTTP 服务）。"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from framework.app import FapApp
from framework.events import EventBus
from framework.gui.panel import Panel

ROOT = Path(__file__).resolve().parents[1]


class ConsoleSnapshotTest(unittest.TestCase):
    def _app(self, folder: str) -> FapApp:
        app = FapApp(root=Path(folder), log_to_file=False)
        app.plugins.plugins_dir = ROOT / "plugins"

        async def boot():
            await app.start(connect=False)

        asyncio.run(boot())
        return app

    def test_status_and_plugins(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(folder)
            panel = Panel(app)
            status = panel.snapshot_status()
            self.assertIn("version", status)
            self.assertIn("stats", status)
            plugins = panel.snapshot_plugins()
            ids = {row["id"] for row in plugins}
            self.assertIn("pet_game", ids)
            self.assertIn("dsh_bridge", ids)
            self.assertTrue(all("command_list" not in row for row in plugins))
            for row in plugins:
                self.assertIn("can_reload", row)

    def test_commands_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(folder)
            rows = Panel(app).snapshot_commands()
            self.assertTrue(any(row["name"] == "help" and row["plugin"] == "framework" for row in rows))
            self.assertTrue(any(row["name"] == "领养" and row["plugin"] == "pet_game" for row in rows))
            self.assertTrue(any(row["plugin"] == "dsh_bridge" for row in rows))

    def test_plugin_actions(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(folder)
            panel = Panel(app)

            async def scenario():
                await app.plugins.unload("pet_game")
                after_disable = {row["id"]: row for row in panel.snapshot_plugins()}
                self.assertFalse(after_disable["pet_game"]["loaded"])
                self.assertFalse(any(c.plugin == "pet_game" for c in app.commands.unique()))
                await app.plugins.load("pet_game")
                after_enable = {row["id"]: row for row in panel.snapshot_plugins()}
                self.assertTrue(after_enable["pet_game"]["loaded"])
                self.assertTrue(any(c.plugin == "pet_game" for c in app.commands.unique()))

            asyncio.run(scenario())
            asyncio.run(app.stop())

    def test_event_history(self) -> None:
        bus = EventBus(history=5)

        async def handler(event="", **payload):
            return None

        bus.on("tick", handler)

        async def scenario():
            for index in range(8):
                await bus.emit("tick", index=index)

        asyncio.run(scenario())
        rows = bus.history()
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[-1]["event"], "tick")
        self.assertEqual(rows[-1]["index"], 7)
        self.assertEqual(bus.history(since=rows[-1]["seq"]), [])

    def test_settings_snapshot_masks_secret(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(folder)
            app.config.update({"appsecret": "top-secret"})
            rows = {row["key"]: row for row in Panel(app).snapshot_settings("")}
            self.assertIn("appid", rows)
            self.assertEqual(rows["appsecret"]["kind"], "secret")
            self.assertEqual(rows["appsecret"]["value"], "***")

    def test_settings_snapshot_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(folder)
            rows = {row["key"]: row for row in Panel(app).snapshot_settings("pet_game")}
            self.assertIn("feed_cooldown_s", rows)
            self.assertEqual(rows["feed_cooldown_s"]["kind"], "int")

    def test_plugin_detail(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(folder)
            # 页面注册需要有 Panel（GUI 模式）；这里手动挂上再热重载一次
            app.gui = Panel(app)
            asyncio.run(app.plugins.reload("dsh_bridge"))
            detail = Panel(app).snapshot_plugin_detail("dsh_bridge")
            self.assertEqual(detail["id"], "dsh_bridge")
            self.assertGreaterEqual(len(detail["commands"]), 16)
            self.assertGreaterEqual(len(detail["settings"]), 4)
            self.assertTrue(any(page["key"] == "dsh" for page in detail["pages"]))
            self.assertIsNone(Panel(app).snapshot_plugin_detail("nope"))

    def test_issues_and_traffic(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(folder)
            issues = Panel(app).snapshot_issues()
            self.assertTrue(any("AppID" in item["text"] for item in issues))   # 测试环境没填 appid
            app._record_traffic("in")
            app._record_traffic("out")
            data = app.traffic(5)
            self.assertEqual(len(data["buckets"]), 5)
            self.assertEqual(sum(bucket["in"] for bucket in data["buckets"]), 1)
            self.assertEqual(sum(bucket["out"] for bucket in data["buckets"]), 1)

    def test_index_served_without_cache(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(folder)
            html = (ROOT / "framework" / "gui" / "index.html").read_text(encoding="utf-8")
            self.assertIn("/api/status", html)
            self.assertIn("no-store", (ROOT / "framework" / "gui" / "panel.py").read_text(encoding="utf-8"))



if __name__ == "__main__":
    unittest.main()
