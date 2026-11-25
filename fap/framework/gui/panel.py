"""GUI 版本：一个“像应用”的本地控制台。

设计目标（用户要求：框架的意义是便捷管理机器人、插件、事件）：

* **机器人**：在线状态、运行时长、主人、网关/进程信息、启停（dsh_bridge 托管时）
* **插件**：列表、版本、命令数、加载/卸载/热重载（按钮直接生效）
* **命令**：整张命令表的可视化（按插件分组、可搜）
* **事件**：实时事件流（框架内部 EventBus 的历史），用于排障
* **设置**：只读配置快照（密钥打码）+ 日志尾部

非 GUI 版本不会 import 本模块；没有 aiohttp 时自动降级为无界面。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from framework.logging import get

log = get("gui")

STATIC_DIR = Path(__file__).resolve().parent


class Panel:
    """本地控制台（aiohttp，无外部前端依赖）。"""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.pages: Dict[str, Dict[str, Any]] = {}
        self.cards: Dict[str, Dict[str, Any]] = {}
        self._runner: Any = None
        self._site: Any = None
        self._started_at = 0.0

    # -- 插件页面注册（保留框架能力） --------------------------------------
    def register_page(self, key: str, title: str, render, *, plugin: str = "") -> None:
        self.pages[key] = {"title": title, "render": render, "plugin": plugin}

    def register_card(self, key: str, render, *, plugin: str = "") -> None:
        self.cards[key] = {"render": render, "plugin": plugin}

    def unregister_plugin(self, plugin: str) -> None:
        self.pages = {key: value for key, value in self.pages.items() if value.get("plugin") != plugin}
        self.cards = {key: value for key, value in self.cards.items() if value.get("plugin") != plugin}

    # -- 生命周期 -----------------------------------------------------------
    async def start(self) -> None:
        try:
            from aiohttp import web
        except Exception as error:  # noqa: BLE001 - 没装 aiohttp 就当没有 GUI
            log.warning("aiohttp missing (%s); panel disabled", error)
            self.app.gui = None
            return
        application = web.Application()
        application.router.add_get("/", self._index)
        application.router.add_get("/api/status", self._api_status)
        application.router.add_get("/api/plugins", self._api_plugins)
        application.router.add_post("/api/plugins/{plugin_id}/{action}", self._api_plugin_action)
        application.router.add_get("/api/commands", self._api_commands)
        application.router.add_get("/api/events", self._api_events)
        application.router.add_get("/api/logs", self._api_logs)
        application.router.add_get("/api/config", self._api_config)
        application.router.add_get("/api/pages/{key}", self._api_page)
        self._runner = web.AppRunner(application)
        await self._runner.setup()
        host = str(self.app.config.get("gui_host", "127.0.0.1"))
        port = int(self.app.config.get("gui_port", 39080))
        self._site = web.TCPSite(self._runner, host, port)
        await self._site.start()
        self._started_at = time.time()
        log.info("console on http://%s:%s/", host, port)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
            self._site = None

    # -- 页面 ---------------------------------------------------------------
    async def _index(self, request: Any) -> Any:
        from aiohttp import web

        html_path = STATIC_DIR / "index.html"
        try:
            body = html_path.read_text(encoding="utf-8")
        except OSError:
            body = "<h1>fap console</h1><p>index.html 缺失</p>"
        return web.Response(text=body, content_type="text/html")

    # -- API ---------------------------------------------------------------
    async def _api_status(self, request: Any) -> Any:
        from aiohttp import web

        if not self._authorised(request):
            return self._denied()
        return web.json_response(self.snapshot_status())

    async def _api_plugins(self, request: Any) -> Any:
        from aiohttp import web

        if not self._authorised(request):
            return self._denied()
        return web.json_response(self.snapshot_plugins())

    async def _api_commands(self, request: Any) -> Any:
        from aiohttp import web

        if not self._authorised(request):
            return self._denied()
        return web.json_response(self.snapshot_commands())

    async def _api_events(self, request: Any) -> Any:
        from aiohttp import web

        if not self._authorised(request):
            return self._denied()
        try:
            since = int(request.query.get("since", "0"))
        except ValueError:
            since = 0
        return web.json_response({"ok": True, "events": self.app.events.history(since=since, limit=120)})

    async def _api_logs(self, request: Any) -> Any:
        from aiohttp import web

        if not self._authorised(request):
            return self._denied()
        try:
            lines = max(1, min(500, int(request.query.get("lines", "120"))))
        except ValueError:
            lines = 120
        return web.json_response({"ok": True, "lines": self.snapshot_logs(lines)})

    async def _api_config(self, request: Any) -> Any:
        from aiohttp import web

        if not self._authorised(request):
            return self._denied()
        return web.json_response({"ok": True, "config": self.app.config.snapshot()})

    async def _api_plugin_action(self, request: Any) -> Any:
        """插件热操作：reload / disable / enable。"""
        from aiohttp import web

        if not self._authorised(request):
            return self._denied()
        plugin_id = request.match_info.get("plugin_id", "")
        action = request.match_info.get("action", "")
        try:
            if action == "reload":
                await self.app.plugins.reload(plugin_id)
            elif action == "disable":
                await self.app.plugins.unload(plugin_id)
            elif action == "enable":
                await self.app.plugins.load(plugin_id)
            else:
                return web.json_response({"ok": False, "error": "unknown action"}, status=400)
        except Exception as error:  # noqa: BLE001 - 操作失败要回给界面
            log.exception("plugin action failed: %s", error)
            return web.json_response({"ok": False, "error": str(error)}, status=500)
        return web.json_response({"ok": True, "plugins": self.snapshot_plugins()})

    async def _api_page(self, request: Any) -> Any:
        from aiohttp import web

        if not self._authorised(request):
            return self._denied()
        key = request.match_info.get("key", "")
        page = self.pages.get(key)
        if page is None:
            return web.json_response({"ok": False, "error": "no such page"}, status=404)
        try:
            data = page["render"]()
            if hasattr(data, "__await__"):
                data = await data
        except Exception as error:  # noqa: BLE001
            return web.json_response({"ok": False, "error": str(error)}, status=500)
        return web.json_response({"ok": True, "key": key, "title": page["title"], "data": data})

    # -- 快照（也被测试直接调用） -------------------------------------------
    def snapshot_status(self) -> Dict[str, Any]:
        base = self.app.status()
        base["console_uptime_s"] = int(time.time() - self._started_at) if self._started_at else 0
        base["pages"] = [{"key": key, "title": value["title"]} for key, value in self.pages.items()]
        return base

    def snapshot_plugins(self) -> List[Dict[str, Any]]:
        rows = self.app.plugins.status()
        for row in rows:
            row["can_reload"] = row["loaded"]
        return rows

    def snapshot_commands(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for command in self.app.commands.unique():
            rows.append(
                {
                    "name": command.name,
                    "aliases": list(command.aliases),
                    "usage": command.usage,
                    "summary": command.summary,
                    "scope": command.scope,
                    "owner_only": command.owner_only,
                    "plugin": command.plugin or "framework",
                    "hidden": command.hidden,
                }
            )
        return rows

    def snapshot_logs(self, lines: int = 120) -> List[str]:
        path = Path(self.app.root) / str(self.app.config.get("log_dir", "session/logs")) / "fap.log"
        try:
            rows = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ["（还没有日志）"]
        return rows[-lines:]

    # -- 鉴权 ---------------------------------------------------------------
    def _authorised(self, request: Any) -> bool:
        token = str(self.app.config.get("gui_token", "") or "")
        if not token:
            return True
        given = request.query.get("token") or request.headers.get("x-fap-token", "")
        return str(given) == token

    @staticmethod
    def _denied() -> Any:
        from aiohttp import web

        return web.json_response({"ok": False, "error": "bad token"}, status=401)
