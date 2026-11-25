"""FapApp：把配置、事件、命令、插件、定时器、QQ、GUI 装配起来。

生命周期：

    app = FapApp(root=".")
    await app.start()      # 载入插件 → 启动定时器 → （GUI）起面板 → 连 QQ
    await app.stop()

业务内容一行都不在这里：框架只负责流程与通用能力。
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from framework import logging as fap_logging
from framework.bot import QQBot
from framework.commands import CommandTable
from framework.config import Config
from framework.storage import JsonStore
from framework.events import EventBus
from framework.plugin import PluginManager
from framework.scheduler import Scheduler
from framework.types import Message, Target

log = fap_logging.get("app")


class FapApp:
    def __init__(
        self,
        root: Optional[Path] = None,
        *,
        gui: bool = False,
        config_path: Optional[Path] = None,
        plugins_dir: Optional[Path] = None,
        log_to_file: bool = True,
    ) -> None:
        self.root = Path(root or Path.cwd()).resolve()
        self.config = Config(config_path or (self.root / "config.json"))
        if gui:
            self.config.update({"gui": True})
        self.logger = fap_logging.configure(
            log_dir=(self.root / str(self.config.get("log_dir", "session/logs"))) if log_to_file else None
        )
        self.events = EventBus()
        self.commands = CommandTable(prefix=str(self.config.get("command_prefix", "/")))
        self.scheduler = Scheduler()
        self.plugins = PluginManager(self, plugins_dir or (self.root / str(self.config.get("plugins_dir", "plugins"))))
        self.bot = QQBot(self)
        self.gui: Any = None
        self.started_at = 0.0
        self._running = False
        self._frame_store = JsonStore(self.state_dir / "framework.json", {"owner": ""})
        stored_owner = str(self._frame_store.get("owner", "") or "")
        configured = list(self.config.owner_ids())
        self._owner_openid = configured[0] if configured else stored_owner
        self._send_window: Dict[str, list] = {}
        self._stats: Dict[str, int] = {"in": 0, "out": 0, "commands": 0, "errors": 0}

    # -- 路径 ---------------------------------------------------------------
    @property
    def state_dir(self) -> Path:
        path = self.root / str(self.config.get("state_dir", "session/state"))
        path.mkdir(parents=True, exist_ok=True)
        return path

    def plugin_state_dir(self, plugin_id: str) -> Path:
        path = self.state_dir / plugin_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    # -- 策略 ---------------------------------------------------------------
    def in_quiet_hours(self) -> bool:
        """支持 "23:30-07:00" 这种跨零点区间；留空表示不启用。"""
        raw = str(self.config.get("quiet_hours", "") or "").strip()
        if not raw or "-" not in raw:
            return False
        try:
            start_text, end_text = raw.split("-", 1)
            start_h, start_m = [int(part) for part in start_text.strip().split(":")]
            end_h, end_m = [int(part) for part in end_text.strip().split(":")]
        except ValueError:
            log.warning("bad quiet_hours: %r", raw)
            return False
        now = time.localtime()
        minutes = now.tm_hour * 60 + now.tm_min
        start = start_h * 60 + start_m
        end = end_h * 60 + end_m
        if start == end:
            return False
        if start < end:
            return start <= minutes < end
        return minutes >= start or minutes < end

    def _rate_limited(self, conv_key: str) -> bool:
        limit = int(self.config.get("rate_limit_per_hour", 0) or 0)
        if limit <= 0:
            return False
        now = time.time()
        window = [stamp for stamp in self._send_window.get(conv_key, []) if now - stamp < 3600]
        if len(window) >= limit:
            self._send_window[conv_key] = window
            return True
        window.append(now)
        self._send_window[conv_key] = window
        return False

    # -- 主人 ---------------------------------------------------------------
    def is_owner(self, openid: str) -> bool:
        if not openid:
            return False
        if openid in set(self.config.owner_ids()):
            return True
        if not self._owner_openid and self.config.get("claim_owner", True):
            self._owner_openid = openid
            self._frame_store.set("owner", openid)
            log.info("owner claimed by first message: %s（已落盘）", openid[-6:])
            return True
        return openid == self._owner_openid

    # -- 生命周期 -----------------------------------------------------------
    def _register_core_commands(self) -> None:
        """框架自带的通用命令：/help /ping /plugins /version（不属于任何插件）。"""
        table = self.commands

        @table.command("help", aliases=("帮助", "指令"), summary="看命令表", order=1)
        async def _help(context) -> None:
            await context.say(table.help_text(scope="group" if context.message.is_group else "c2c", is_owner=context.is_owner))

        @table.command("ping", summary="测活", order=2)
        async def _ping(context) -> None:
            await context.say("pong（运行 " + str(self.status()["uptime_s"]) + "s）")

        @table.command("plugins", aliases=("插件",), summary="插件与加载状态", order=3)
        async def _plugins(context) -> None:
            rows = ["**插件**"]
            for item in self.plugins.status():
                mark = "✅" if item["loaded"] else "—"
                rows.append(mark + " " + item["id"] + " v" + item["version"] + "（" + str(item["commands"]) + " 条命令）")
            await context.say(chr(10).join(rows))

        @table.command("version", aliases=("版本",), summary="框架版本", order=4)
        async def _version(context) -> None:
            import framework

            await context.say("fap " + framework.__version__ + " · 插件 " + str(len(self.plugins.loaded)) + " 个")

        @table.command("reload", summary="热重载某个插件", usage="<插件id>", owner_only=True, order=5)
        async def _reload(context) -> None:
            if not context.args:
                context.fail("用法：/reload <插件id>，可用 " + ", ".join(self.plugins.manifests.keys()))
            target = context.args[0]
            await self.plugins.reload(target)
            await context.say("已重载 " + target)

    async def start(self, *, connect: bool = True) -> None:
        self.started_at = time.time()
        self._register_core_commands()
        await self.events.emit("app.starting", app=self)
        loaded = await self.plugins.load_all(self.config.get("enabled_plugins") or None)
        log.info("plugins loaded: %s", ", ".join(loaded) or "(none)")
        await self.scheduler.start()
        if self.config.get("gui"):
            await self.start_gui()
        await self.events.emit("app.ready", app=self)
        self._running = True
        if connect and self.config.get("connect_qq", True):
            self.bot.start_background()
        elif connect:
            log.info("connect_qq=false：框架不连 QQ（由插件托管外部机器人）")

    async def start_gui(self) -> None:
        try:
            from framework.gui.panel import Panel  # 只有 GUI 版本才 import aiohttp
        except Exception as error:  # noqa: BLE001 - 没装 aiohttp 就降级成无界面
            log.warning("gui unavailable (%s); running headless", error)
            return
        self.gui = Panel(self)
        await self.gui.start()

    async def stop(self) -> None:
        self._running = False
        await self.events.emit("app.stopping", app=self)
        if self.gui is not None:
            await self.gui.stop()
        await self.plugins.unload_all()
        await self.scheduler.stop()
        fap_logging.shutdown()

    def run(self, *, connect: bool = True) -> None:
        """同步入口：起事件循环 → start → （GUI 下阻塞在面板；否则阻塞在 QQ）。"""
        async def _boot() -> None:
            await self.start(connect=connect)
            if connect and not self.config.get("gui"):
                # 非 GUI：QQ 客户端自己会阻塞，这里用事件等待保持循环存活
                await asyncio.Event().wait()
            elif self.gui is None:
                await asyncio.Event().wait()
            else:
                await asyncio.Event().wait()

        asyncio.run(_boot())

    # -- 入站总入口 ---------------------------------------------------------
    async def on_message(self, message: Message) -> None:
        self._stats["in"] += 1
        self._stats["errors"] = self._stats.get("errors", 0)
        start = time.time()
        log.info("in %s %s: %r", message.kind, message.sender.short, (message.text or "")[:60])
        try:
            if not self._allowed(message):
                return
            is_command = self.commands.resolve(message.text) is not None
            if not is_command and self.in_quiet_hours():
                log.info("quiet hours: chatter suppressed in %s", message.conv_key)
                return
            await self.events.emit("message", app=self, message=message)
            handled = await self.commands.dispatch(self, message)
            if handled:
                self._stats["commands"] += 1
                return
            await self.events.emit("message.unhandled", app=self, message=message)
        except Exception as error:  # noqa: BLE001 - 单条消息永远不能拖垮进程
            self._stats["errors"] += 1
            log.exception("message handling failed: %s", error)
        finally:
            await self.events.emit(
                "message.done",
                app=self,
                message=message,
                elapsed=time.time() - start,
            )

    def _allowed(self, message: Message) -> bool:
        if message.kind == "group" and not self.config.get("group_enabled", True):
            return False
        if message.kind == "c2c" and not self.config.get("c2c_enabled", True):
            return False
        groups = self.config.get("allowlist_groups") or []
        users = self.config.get("allowlist_c2c") or []
        if message.kind == "group" and groups and message.target.openid not in groups:
            return False
        if message.kind == "c2c" and users and message.target.openid not in users:
            return False
        return True

    # -- 出站 ---------------------------------------------------------------
    async def send(self, target: Target, text: str, **kwargs: Any) -> Any:
        if not str(text or "").strip():
            return None
        if self._rate_limited(target.conv_key):
            log.warning("rate limit hit in %s; outbound dropped", target.conv_key)
            return None
        self._stats["out"] += 1
        await self.events.emit("outbound", app=self, target=target, text=text)
        return await self.bot.send(target, text, **kwargs)

    async def say(self, conv_key: str, text: str, **kwargs: Any) -> Any:
        return await self.send(Target.from_key(conv_key), text, **kwargs)

    # -- SDK 回调 -----------------------------------------------------------
    async def on_bot_ready(self) -> None:
        log.info("bot online (owner=%s)", (self._owner_openid or "unclaimed")[-6:])
        await self.events.emit("bot.ready", app=self)

    async def on_interaction(self, interaction: Any) -> None:
        """按钮点击等交互：原样转给插件（插件用 events.on("interaction") 处理）。"""
        await self.events.emit("interaction", app=self, interaction=interaction)

    # -- 状态 ---------------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        return {
            "version": __import__("framework").__version__,
            "uptime_s": int(time.time() - self.started_at) if self.started_at else 0,
            "gui": self.gui is not None,
            "owner": (self._owner_openid or "")[-6:],
            "stats": dict(self._stats),
            "plugins": self.plugins.status(),
            "commands": len(self.commands.unique()),
            "jobs": [{"name": job.name, "runs": job.runs, "errors": job.errors} for job in self.scheduler.jobs()],
        }
