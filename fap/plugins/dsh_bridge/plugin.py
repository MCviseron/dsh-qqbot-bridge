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

# 框架侧能自己实现的命令
FRAMEWORK_COMMANDS = (
    ("dsh", ("桥接",), "[status|start|stop|restart|logs|panel|命令]", "桥接状态与启停"),
    ("状态", ("status",), "", "读旧机器人面板的实时状态（需要它在线）"),
    ("日志", ("dsh-log",), "[行数]", "旧机器人日志尾部"),
    ("面板", ("panel",), "", "DSH 面板地址"),
)

# 旧机器人（legacy/bot）才有的命令：这里登记是为了“不漏”，并明确告诉用户去哪儿用
LEGACY_COMMANDS = (
    ("绑定", ("绑定主人",), "把当前群主绑定成机器人主人"),
    ("重置", ("新会话", "清空"), "清空 DSH 会话上下文"),
    ("分组", ("workspace", "ws"), "把会话迁到独立工作区"),
    ("菜单", ("menu", "commands"), "列出 DSH 官方指令（框架命令用 /help）"),
    ("pr", (), "查看/切换权限预设"),
    ("链接", ("邀请", "invite"), "机器人邀请链接"),
    ("截图", ("screenshot", "shot"), "截屏发到会话"),
    ("窗口", ("windows",), "列出可截窗口"),
    ("会话", ("sessions",), "列出 DSH 会话"),
    ("切会话", ("切换", "switch"), "切到指定会话"),
    ("切回", ("返回", "back"), "切回原会话"),
    ("花费", ("用量", "usage", "cost", "token"), "看 token 用量"),
    ("撤回", ("recall",), "撤回上一条消息"),
    ("消息池", ("池", "pool"), "看当前消息池"),
)

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
        # 旧机器人专有命令：登记进表（/help 能看到、输错时能被告知去哪用）
        for name, aliases, summary in LEGACY_COMMANDS:
            self._register_legacy_command(ctx, name, aliases, summary)

        @ctx.command("日志", aliases=("dsh-log",), summary="旧机器人日志尾部", usage="[行数]", order=9)
        async def _logs(context) -> None:
            limit = 12
            if context.args:
                try:
                    limit = max(1, min(200, int(context.args[0])))
                except ValueError:
                    limit = 12
            await context.say(self.tail_logs(limit))

        @ctx.command("面板", aliases=("panel",), summary="DSH 面板地址", order=9)
        async def _panel(context) -> None:
            await context.say("DSH 面板：" + str(self.cfg("panel_url")) + "\n（机器人进程在跑时可用）")

        @ctx.command("状态", aliases=("status",), summary="读旧机器人面板的实时状态", order=8)
        async def _state(context) -> None:
            await context.say(await self.remote_state_text())

        @ctx.command("dsh", aliases=("桥接",), summary="DSH 桥接状态/启停/日志", usage="[status|start|stop|restart|logs|panel|命令]", order=10)
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
            elif action in ("命令", "help", "cmd"):
                await context.say(self.command_overview())
            else:
                context.fail("用法：" + context.command.help_line(self.ctx.commands.prefix))


    def _register_legacy_command(self, ctx: PluginContext, name: str, aliases, summary: str) -> None:
        """旧机器人专有命令：登记进表，回复里说清楚去哪儿用。"""
        hint = (
            "「/" + name + "」由旧机器人处理（它才是 QQ 网关时可用）。\n"
            "当前框架模式下等价能力："
        )
        equivalents = {
            "绑定": "框架用 config.json 的 owners 列表指定主人",
            "重置": "框架暂无（DSH 会话由 dsh_bridge 托管进程管理）",
            "分组": "框架暂无（每个会话共用项目根目录）",
            "指令": "框架用 /help 看本框架命令",
            "pr": "框架暂无（权限由 DSH 会话自身管）",
            "链接": "框架暂无（邀请链接需要平台接口）",
            "截图": "框架暂无（截图发图由旧机器人实现）",
            "窗口": "框架暂无",
            "会话": "框架用 /plugins 看插件；会话列表在 DSH 面板",
            "切会话": "框架暂无",
            "切回": "框架暂无",
            "花费": "框架暂无（用量在 DSH 面板）",
            "撤回": "框架暂无",
            "消息池": "框架暂无",
        }
        answer = hint + equivalents.get(name, "无")

        async def _legacy(context, _answer: str = answer) -> None:
            await context.say(_answer)

        try:
            ctx.commands.register(
                __import__("framework.commands", fromlist=["Command"]).Command(
                    name=name,
                    handler=_legacy,
                    aliases=tuple(aliases),
                    summary=summary + "（旧机器人专有）",
                    plugin=ctx.id,
                    order=90,
                )
            )
        except ValueError as error:  # 与框架/其它插件的命令重名：跳过，不拖垮插件
            ctx.log.warning("legacy command /%s skipped: %s", name, error)

    async def remote_state_text(self) -> str:
        """读旧机器人的面板 /api/state（没有 token 也能读，面板默认只绑回环）。"""
        import json
        import urllib.request

        url = str(self.cfg("panel_url")).rstrip("/") + "/api/state"
        try:
            with urllib.request.urlopen(url, timeout=4) as response:
                body = json.loads(response.read().decode("utf-8"))
        except Exception as error:  # noqa: BLE001 - 面板没起是常态
            return "读不到旧机器人状态（面板未运行？）：" + str(error)[:80]
        bot = body.get("bot") or {}
        bridge = body.get("bridge") or {}
        lines = [
            "**旧机器人**：" + ("运行中" if bot.get("running") else "未运行")
            + ("，pid " + str(bot.get("pid")) if bot.get("pid") else "")
            + ("，在线" if bot.get("online") else "，离线"),
            "运行时长：" + str(bot.get("uptime_s") or 0) + "s",
            "桥接：" + str(bridge.get("url") or bridge.get("base_url") or "-"),
            "备注：" + str(bot.get("note") or "-"),
        ]
        return "\n".join(lines)

    def command_overview(self) -> str:
        rows = ["**框架可直接用**"]
        for name, aliases, usage, summary in FRAMEWORK_COMMANDS:
            rows.append("  /" + name + ((" " + usage) if usage else "") + " — " + summary)
        rows.append("")
        rows.append("**旧机器人专有（托管模式下由它处理）**")
        for name, aliases, summary in LEGACY_COMMANDS:
            rows.append("  /" + name + " — " + summary)
        return "\n".join(rows)

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
