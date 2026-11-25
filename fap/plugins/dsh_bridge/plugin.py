"""dsh_bridge：QQ ⇄ DSH 桥接插件。

本插件承担两种职责，二选一由配置决定：

1. **进程托管模式（默认）**
   把已有的 QQ⇄DSH 机器人（legacy/bot/main.py）作为受管子进程拉起，框架负责
   命令、状态、日志、面板页与生命周期。此时应把框架自己的 QQ 连接关掉
   （config.connect_qq = false），否则两条网关会抢同一个 AppID。

2. **纯框架模式**
   connect_qq = true 时，框架自己连 QQ；本插件只提供 /dsh 系列命令用于对接
   DSH 面板（健康检查、后台重启等），消息转发留给后续迁移。

为什么先用托管而不是整体重写：现有机器人里有大量已验证的平台细节（流式分帧、
被动回复窗口、审批卡片、文件发送）。框架先把外围（命令表、状态、日志、面板）
接过来，逐块迁移，避免一次性重写出事故。
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from framework.plugin import Plugin, PluginContext

DEFAULTS = {
    "legacy_dir": "legacy/bot",       # 相对项目根目录
    "autostart": False,               # 框架启动时是否拉起旧机器人
    "python": "",                     # 留空 = 当前解释器
    "panel_url": "http://127.0.0.1:39062",
    "log_tail": 12,
}


class DshBridgePlugin(Plugin):
    id = "dsh_bridge"
    name = "QQ ⇄ DSH 桥接"
    version = "0.3.0"
    description = "托管 QQ⇄DSH 机器人进程，并提供状态/日志/启停命令"

    def __init__(self) -> None:
        super().__init__()
        self._child: Optional[subprocess.Popen] = None
        self._started_at = 0.0
        self._log_path: Optional[Path] = None

    # -- 配置 ---------------------------------------------------------------
    def cfg(self, key: str, default: Any = None) -> Any:
        section = dict(DEFAULTS)
        section.update(self.ctx.config() if self.ctx else {})
        return section.get(key, default)

    def legacy_dir(self) -> Path:
        root = Path(getattr(self.ctx.app, "root", Path.cwd()))
        return (root / str(self.cfg("legacy_dir"))).resolve()

    # -- 生命周期 -----------------------------------------------------------
    async def setup(self, ctx: PluginContext) -> None:
        ctx.log.info("dsh_bridge ready (legacy=%s, autostart=%s)", self.legacy_dir(), self.cfg("autostart"))
        self._register_commands(ctx)
        ctx.on("app.ready", self._on_app_ready)
        ctx.on("app.stopping", self._on_app_stopping)
        ctx.page("dsh", "DSH 桥接", self.render_page)
        if self.cfg("autostart"):
            await self.start_bot()

    async def teardown(self) -> None:
        await self.stop_bot()

    # -- 命令 ---------------------------------------------------------------
    def _register_commands(self, ctx: PluginContext) -> None:
        @ctx.command("dsh", summary="DSH 桥接状态/启停/日志", usage="[status|start|stop|restart|logs|panel]", order=10)
        async def _dsh(context) -> None:
            action = (context.args[0].lower() if context.args else "status")
            if action == "status":
                await context.say(self.status_text())
            elif action == "start":
                await context.say(await self.start_bot())
            elif action == "stop":
                await context.say(await self.stop_bot())
            elif action == "restart":
                await self.stop_bot()
                await context.say(await self.start_bot())
            elif action == "logs":
                await context.say(self.tail_logs())
            elif action == "panel":
                await context.say("DSH 面板：" + str(self.cfg("panel_url")) + "\n（需要机器人进程在运行）")
            else:
                context.fail("用法：" + context.command.help_line(self.ctx.commands.prefix))

        @ctx.command("dsh-log", summary="看机器人日志尾部", usage="[行数]", owner_only=True, order=11)
        async def _dsh_log(context) -> None:
            limit = 12
            if context.args:
                try:
                    limit = max(1, min(200, int(context.args[0])))
                except ValueError:
                    limit = 12
            await context.say(self.tail_logs(limit))

    # -- 事件 ---------------------------------------------------------------
    async def _on_app_ready(self, event: str = "", **_: Any) -> None:
        if self.cfg("autostart") and not self.is_running():
            await self.start_bot()

    async def _on_app_stopping(self, event: str = "", **_: Any) -> None:
        await self.stop_bot()

    # -- 进程 ---------------------------------------------------------------
    def is_running(self) -> bool:
        return self._child is not None and self._child.poll() is None

    def _python(self) -> str:
        return str(self.cfg("python") or sys.executable)

    async def start_bot(self) -> str:
        directory = self.legacy_dir()
        entry = directory / "main.py"
        if not entry.exists():
            return "找不到机器人入口：" + str(entry)
        if self.is_running():
            return "机器人已在运行（pid " + str(self._child.pid) + "）"
        logs = directory / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        self._log_path = logs / "bridge.log"
        creation = 0
        if sys.platform.startswith("win"):
            creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            handle = open(self._log_path, "ab", buffering=0)
            self._child = subprocess.Popen(
                [self._python(), "-u", "main.py", "--supervise"],
                cwd=str(directory),
                stdout=handle,
                stderr=subprocess.STDOUT,
                creationflags=creation,
            )
        except Exception as error:  # noqa: BLE001 - 拉不起来要能回话
            self.ctx.log.exception("start failed: %s", error)
            return "启动失败：" + str(error)
        self._started_at = time.time()
        await asyncio.sleep(1.5)
        state = "运行中" if self.is_running() else "启动后立刻退出，看 /dsh-log"
        return "已启动机器人（pid " + str(self._child.pid) + "，日志 " + str(self._log_path) + "）：" + state

    async def stop_bot(self) -> str:
        child = self._child
        if child is None or child.poll() is not None:
            self._child = None
            return "机器人没有在运行"
        try:
            child.terminate()
            try:
                child.wait(timeout=8)
            except subprocess.TimeoutExpired:
                child.kill()
        except Exception as error:  # noqa: BLE001
            return "停止失败：" + str(error)
        self._child = None
        return "已停止机器人"

    # -- 展示 ---------------------------------------------------------------
    def tail_logs(self, limit: int = 12) -> str:
        directory = self.legacy_dir()
        candidates = [directory / "logs" / "bridge.log", directory / "logs" / "viseron_qqbotpy.log"]
        for path in candidates:
            if not path.exists():
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            return "\n".join(lines[-limit:]) or "（日志是空的）"
        return "还没有日志文件（机器人没启动过？）"

    def status_text(self) -> str:
        running = self.is_running()
        uptime = ""
        if running and self._started_at:
            uptime = "，" + str(int(time.time() - self._started_at)) + "s"
        pid = "pid " + str(self._child.pid) + uptime if running else "未运行"
        lines = [
            "**DSH 桥接**：" + ("运行中" if running else "已停止") + "（" + pid + "）",
            "机器人目录：" + str(self.legacy_dir()),
            "DSH 面板：" + str(self.cfg("panel_url")),
            "框架 QQ 连接：" + ("开" if self.ctx.app.config.get("connect_qq", True) else "关"),
        ]
        return "\n".join(lines)

    def render_page(self) -> Dict[str, Any]:
        return {
            "running": self.is_running(),
            "pid": self._child.pid if self.is_running() else None,
            "uptime_s": int(time.time() - self._started_at) if self.is_running() and self._started_at else 0,
            "legacy_dir": str(self.legacy_dir()),
            "panel_url": self.cfg("panel_url"),
            "logs": self.tail_logs(int(self.cfg("log_tail", 12))).splitlines(),
        }
