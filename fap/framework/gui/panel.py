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
        application.router.add_get("/api/traffic", self._api_traffic)
        application.router.add_get("/api/settings", self._api_settings)
        application.router.add_post("/api/settings", self._api_save_settings)
        application.router.add_get("/api/issues", self._api_issues)
        application.router.add_get("/api/plugins/{plugin_id}", self._api_plugin_detail)
        application.router.add_get("/api/pages/{key}", self._api_page)
        # access_log=None：控制台每次轮询都会打一行，不关会把日志刷满
        self._runner = web.AppRunner(application, access_log=None)
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
        # 界面是单文件、随代码更新：禁掉缓存，改完刷新就是最新的
        return web.Response(text=body, content_type="text/html",
                            headers={"Cache-Control": "no-store, must-revalidate"})

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

    async def _api_plugin_detail(self, request: Any) -> Any:
        from aiohttp import web

        if not self._authorised(request):
            return self._denied()
        detail = self.snapshot_plugin_detail(request.match_info.get("plugin_id", ""))
        if detail is None:
            return web.json_response({"ok": False, "error": "no such plugin"}, status=404)
        return web.json_response({"ok": True, "plugin": detail})

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

    async def _api_traffic(self, request: Any) -> Any:
        from aiohttp import web

        if not self._authorised(request):
            return self._denied()
        try:
            minutes = max(5, min(120, int(request.query.get("minutes", "30"))))
        except ValueError:
            minutes = 30
        return web.json_response({"ok": True, **self.app.traffic(minutes)})

    async def _api_settings(self, request: Any) -> Any:
        """owner 为空 = 框架设置；否则是该插件的设置。"""
        from aiohttp import web

        if not self._authorised(request):
            return self._denied()
        owner = str(request.query.get("owner", "") or "")
        return web.json_response({"ok": True, "owner": owner, "fields": self.snapshot_settings(owner)})

    async def _api_save_settings(self, request: Any) -> Any:
        from aiohttp import web

        if not self._authorised(request):
            return self._denied()
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001
            payload = {}
        owner = str((payload or {}).get("owner") or "")
        values = (payload or {}).get("values") or {}
        if not isinstance(values, dict):
            return web.json_response({"ok": False, "error": "values must be an object"}, status=400)
        try:
            self.app.save_settings(values, owner=owner)
        except Exception as error:  # noqa: BLE001
            log.exception("save settings failed: %s", error)
            return web.json_response({"ok": False, "error": str(error)}, status=500)
        return web.json_response({"ok": True, "fields": self.snapshot_settings(owner)})

    async def _api_issues(self, request: Any) -> Any:
        from aiohttp import web

        if not self._authorised(request):
            return self._denied()
        return web.json_response({"ok": True, "issues": self.snapshot_issues()})

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
        base["pages"] = self.custom_pages()
        base["gui_mode"] = str(self.app.config.get("gui_mode", "app"))
        base["issues"] = self.snapshot_issues()
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
                    "requires": command.requires,
                    "plugin": command.plugin or "framework",
                    "hidden": command.hidden,
                }
            )
        return rows

    def snapshot_settings(self, owner: str = "") -> List[Dict[str, Any]]:
        config = self.app.config
        snapshot = config.snapshot(mask_secrets=False)
        section = snapshot.get("plugins", {}).get(owner, {}) if owner else snapshot
        rows: List[Dict[str, Any]] = []
        for spec in self.app.settings.specs(owner):
            value = section.get(spec.key, spec.default)
            if spec.kind == "secret" and value:
                value = "***"
            rows.append(
                {
                    "key": spec.key,
                    "label": spec.label,
                    "kind": spec.kind,
                    "value": value,
                    "default": spec.default,
                    "help": spec.help,
                    "choices": spec.choices,
                    "owner": owner,
                }
            )
        return rows

    def snapshot_issues(self) -> List[Dict[str, str]]:
        """一眼能看懂的“现在有什么不对”：缺凭据、插件没加载、没声明设置等。"""
        issues: List[Dict[str, str]] = []
        config = self.app.config
        if not str(config.get("appid") or "").strip():
            issues.append({"level": "error", "text": "缺少 AppID，机器人无法登录 QQ"})
        if not str(config.get("appsecret") or "").strip():
            issues.append({"level": "error", "text": "缺少 AppSecret，机器人无法登录 QQ"})
        if not str(config.get("connect_qq", True)):
            issues.append({"level": "info", "text": "connect_qq=false：框架不会连 QQ（由插件托管外部机器人）"})
        for row in self.app.plugins.status():
            if not row["loaded"]:
                issues.append({"level": "warn", "text": "插件未加载：" + str(row["id"])})
            elif row["commands"] == 0:
                issues.append({"level": "info", "text": "插件没有命令：" + str(row["id"])})
            if row["loaded"] and not self.app.settings.specs(str(row["id"])):
                issues.append({"level": "info", "text": "插件没有声明设置项：" + str(row["id"])})
        if not self.custom_pages():
            issues.append({"level": "info", "text": "没有插件注册页面（ctx.page）"})
        return issues

    def custom_pages(self) -> List[Dict[str, str]]:
        source = self.app.gui.pages if getattr(self.app, "gui", None) is not None else self.pages
        return [{"key": key, "title": value["title"], "plugin": value.get("plugin", "")}
                for key, value in source.items()]

    def snapshot_plugin_detail(self, plugin_id: str) -> Optional[Dict[str, Any]]:
        manifest = self.app.plugins.manifests.get(plugin_id)
        if manifest is None:
            return None
        return {
            "id": manifest.id,
            "name": manifest.name,
            "version": manifest.version,
            "description": manifest.description,
            "author": manifest.author,
            "path": str(manifest.path),
            "loaded": plugin_id in self.app.plugins.loaded,
            "requires_gui": manifest.requires_gui,
            "commands": [
                {
                    "name": command.name,
                    "aliases": list(command.aliases),
                    "usage": command.usage,
                    "summary": command.summary,
                    "scope": command.scope,
                    "requires": command.requires,
                }
                for command in self.app.commands.unique()
                if command.plugin == plugin_id
            ],
            "settings": self.snapshot_settings(plugin_id),
            "pages": [page for page in self.custom_pages() if page["plugin"] == plugin_id],
        }

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
