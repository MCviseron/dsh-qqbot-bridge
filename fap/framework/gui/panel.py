"""可选的本地 Web 面板（GUI 版本）。

插件通过 ctx.page() / ctx.card() 注册内容；框架负责路由、鉴权、渲染。
非 GUI 模式不会加载本模块。
"""

from __future__ import annotations

import html
import json
from typing import Any, Callable, Dict, List, Optional

from framework.logging import get

log = get("gui")


class Panel:
    def __init__(self, app: Any) -> None:
        self.app = app
        self.pages: Dict[str, Dict[str, Any]] = {}
        self.cards: Dict[str, Dict[str, Any]] = {}
        self._runner: Any = None
        self._site: Any = None

    # -- 注册 ---------------------------------------------------------------
    def register_page(self, key: str, title: str, render: Callable[[], Any], *, plugin: str = "") -> None:
        self.pages[key] = {"title": title, "render": render, "plugin": plugin}

    def register_card(self, key: str, render: Callable[[], Any], *, plugin: str = "") -> None:
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
        application.router.add_get("/api/pages", self._api_pages)
        application.router.add_get("/api/pages/{key}", self._api_page)
        self._runner = web.AppRunner(application)
        await self._runner.setup()
        self._site = web.TCPSite(
            self._runner,
            str(self.app.config.get("gui_host", "127.0.0.1")),
            int(self.app.config.get("gui_port", 39080)),
        )
        await self._site.start()
        log.info(
            "panel on http://%s:%s/",
            self.app.config.get("gui_host", "127.0.0.1"),
            self.app.config.get("gui_port", 39080),
        )

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
            self._site = None

    # -- 路由 ---------------------------------------------------------------
    async def _index(self, request: Any) -> Any:
        from aiohttp import web

        status = self.app.status()
        rows = "".join(
            "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                html.escape(str(item["id"])),
                html.escape(str(item["version"])),
                "✅" if item["loaded"] else "—",
                html.escape(str(item["description"])),
            )
            for item in status["plugins"]
        )
        pages = "".join(
            '<li><a href="/api/pages/{}">{}</a></li>'.format(html.escape(key), html.escape(value["title"]))
            for key, value in self.pages.items()
        )
        body = (
            "<html><head><meta charset='utf-8'><title>fap</title>"
            "<style>body{font:14px system-ui;margin:24px;max-width:900px}"
            "table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #ddd;padding:6px;text-align:left}"
            "code{background:#f3f3f3;padding:1px 4px;border-radius:3px}</style></head><body>"
            "<h1>fap framework</h1>"
            "<p>版本 <code>{version}</code> · 运行 {uptime_s}s · 主人 <code>{owner}</code> · 命令 {commands} 条</p>"
            "<h2>插件</h2><table><tr><th>id</th><th>版本</th><th>已加载</th><th>说明</th></tr>{rows}</table>"
            "<h2>页面</h2><ul>{pages}</ul>"
            "<p><a href='/api/status'>/api/status</a> · <a href='/api/pages'>/api/pages</a></p>"
            "</body></html>"
        ).format(
            version=html.escape(str(status["version"])),
            uptime_s=status["uptime_s"],
            owner=html.escape(str(status["owner"] or "-")),
            commands=status["commands"],
            rows=rows,
            pages=pages or "<li>（没有插件页面）</li>",
        )
        return web.Response(text=body, content_type="text/html")

    async def _api_status(self, request: Any) -> Any:
        from aiohttp import web

        if not self._authorised(request):
            return web.json_response({"ok": False, "error": "bad token"}, status=401)
        return web.json_response(self.app.status())

    async def _api_pages(self, request: Any) -> Any:
        from aiohttp import web

        if not self._authorised(request):
            return web.json_response({"ok": False, "error": "bad token"}, status=401)
        return web.json_response(
            {"ok": True, "pages": [{"key": key, "title": value["title"]} for key, value in self.pages.items()]}
        )

    async def _api_page(self, request: Any) -> Any:
        from aiohttp import web

        if not self._authorised(request):
            return web.json_response({"ok": False, "error": "bad token"}, status=401)
        key = request.match_info.get("key", "")
        page = self.pages.get(key)
        if page is None:
            return web.json_response({"ok": False, "error": "no such page"}, status=404)
        try:
            data = page["render"]()
            if hasattr(data, "__await__"):
                data = await data
        except Exception as error:  # noqa: BLE001 - 页面渲染失败要能看到原因
            return web.json_response({"ok": False, "error": str(error)}, status=500)
        return web.json_response({"ok": True, "key": key, "title": page["title"], "data": data})

    def _authorised(self, request: Any) -> bool:
        token = str(self.app.config.get("gui_token", "") or "")
        if not token:
            return True
        given = request.query.get("token") or request.headers.get("x-fap-token", "")
        return str(given) == token


def jsonify(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
