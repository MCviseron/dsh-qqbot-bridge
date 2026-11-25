"""fap framework — QQ bot 的框架核心（GUI 与非 GUI 共用）。

框架只提供"能力"，业务全部落在插件里：

    from framework import FapApp, Plugin, PluginContext

    app = FapApp()                 # 非 GUI
    app = FapApp(gui=True)         # GUI（额外起一个本地面板）
    app.load_plugins()             # 发现并装配插件
    app.run()                      # 连接 QQ 并进入事件循环

约定：
* 命令一律走 CommandTable（表驱动，不在业务代码里写 if text == "/xx"）；
* 事件一律走 EventBus（插件之间不直接互相 import）；
* 插件只通过 PluginContext 拿能力（日志、存储、命令、事件、定时器、GUI 页面）；
* 配置按插件命名空间隔离：session/config.json 的 plugins.<id> 段。
"""

from framework.app import FapApp
from framework.bot import QQBot
from framework.commands import Command, CommandContext, CommandTable
from framework.config import Config
from framework.events import EventBus
from framework.plugin import Plugin, PluginContext, PluginManager, PluginManifest
from framework.scheduler import Scheduler
from framework.storage import JsonStore, JsonlStore
from framework.types import Message, Outgoing, Sender, Target

__version__ = "0.1.0"

__all__ = [
    "FapApp",
    "QQBot",
    "Command",
    "CommandContext",
    "CommandTable",
    "Config",
    "EventBus",
    "Plugin",
    "PluginContext",
    "PluginManager",
    "PluginManifest",
    "Scheduler",
    "JsonStore",
    "JsonlStore",
    "Message",
    "Outgoing",
    "Sender",
    "Target",
    "__version__",
]
