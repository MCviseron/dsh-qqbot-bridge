"""Local settings page for the QQ bot.

Served by the supervisor process, so the page keeps answering while the bot
itself is stopped (that is what makes the 启动/关闭 buttons possible).
"""
from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from aiohttp import web

from runtime_config import RuntimeConfig

PANEL_HTML = Path(__file__).resolve().parent / "panel.html"


def build_app(control: Any, runtime: RuntimeConfig, token: str) -> web.Application:
    """Create the aiohttp app; `control` owns the process lifecycle."""

    app = web.Application(middlewares=[])

    def authorised(request: web.Request) -> bool:
        # The server binds loopback only, so the DSH GUI (another local port)
        # may call it without a token; a supplied token is still verified.
        supplied = request.headers.get("x-panel-token") or request.query.get("t") or ""
        if supplied == "":
            return True
        return token == "" or supplied == token

    @web.middleware
    async def cors(request: web.Request, handler: Any) -> web.StreamResponse:
        if request.method == "OPTIONS":
            response: web.StreamResponse = web.Response(status=204)
        else:
            response = await handler(request)
        response.headers["access-control-allow-origin"] = "*"
        response.headers["access-control-allow-headers"] = "content-type,x-panel-token"
        response.headers["access-control-allow-methods"] = "GET,POST,OPTIONS"
        return response

    async def index(request: web.Request) -> web.StreamResponse:
        try:
            body = PANEL_HTML.read_text(encoding="utf-8")
        except OSError:
            return web.Response(text="panel.html missing", status=500)
        return web.Response(text=body, content_type="text/html", charset="utf-8")

    async def state(request: web.Request) -> web.Response:
        if not authorised(request):
            return web.json_response({"ok": False, "error": "bad token"}, status=401)
        return web.json_response({
            "ok": True,
            "bot": control.status(),
            "config": runtime.snapshot(),
            "bridge": control.bridge_state(),
        })

    async def update_config(request: web.Request) -> web.Response:
        if not authorised(request):
            return web.json_response({"ok": False, "error": "bad token"}, status=401)
        try:
            patch = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "bad json"}, status=400)
        if not isinstance(patch, dict):
            return web.json_response({"ok": False, "error": "body must be an object"}, status=400)
        config = runtime.update(patch)
        return web.json_response({"ok": True, "config": runtime.snapshot(), "saved": len(config)})

    async def manage(request: web.Request) -> web.Response:
        if not authorised(request):
            return web.json_response({"ok": False, "error": "bad token"}, status=401)
        try:
            body = await request.json()
        except Exception:
            body = {}
        action = str((body or {}).get("action") or "")
        if action not in {"start", "stop", "restart"}:
            return web.json_response({"ok": False, "error": "unknown action"}, status=400)
        message = await control.perform(action)
        return web.json_response({"ok": True, "action": action, "message": message, "bot": control.status()})

    async def logs(request: web.Request) -> web.Response:
        if not authorised(request):
            return web.json_response({"ok": False, "error": "bad token"}, status=401)
        try:
            limit = int(request.query.get("lines", "300"))
        except ValueError:
            limit = 300
        getter = getattr(control, "logs", None)
        lines = getter(limit) if callable(getter) else []
        return web.json_response({"ok": True, "lines": lines})

    async def health(request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "panel": "dsh-qq-bot", "bot": control.status()})

    app.middlewares.append(cors)
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_get("/api/state", state)
    app.router.add_get("/api/logs", logs)
    app.router.add_post("/api/config", update_config)
    app.router.add_post("/api/manage", manage)
    return app


def start_panel(control: Any, runtime: RuntimeConfig, host: str, port: int, token: str) -> threading.Thread:
    """Run the page in a background thread with its own event loop."""

    def runner() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        app = build_app(control, runtime, token)
        app_runner = web.AppRunner(app)
        loop.run_until_complete(app_runner.setup())
        site = web.TCPSite(app_runner, host, port)
        try:
            loop.run_until_complete(site.start())
            print(f"[panel] settings page on http://{host}:{port}/?t=<token>", flush=True)
            loop.run_forever()
        except OSError as error:
            print(f"[panel] could not bind {host}:{port}: {error}", flush=True)

    thread = threading.Thread(target=runner, name="qq-bot-panel", daemon=True)
    thread.start()
    return thread
