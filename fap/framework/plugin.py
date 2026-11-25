"""插件契约 + 插件管理器。

一个插件就是一个目录：

    plugins/pet_game/
        manifest.json      # id / name / version / entry / gui
        plugin.py          # class PetPlugin(Plugin)
        ...

插件能拿到的能力全部经由 PluginContext，不允许自己 import 框架内部模块。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from framework.commands import CommandContext, CommandTable
from framework.events import EventBus
from framework.logging import get
from framework.scheduler import Scheduler
from framework.storage import JsonStore, JsonlStore

log = get("plugin")


@dataclass
class PluginManifest:
    id: str
    name: str = ""
    version: str = "0.0.0"
    description: str = ""
    entry: str = "plugin.py"
    class_name: str = ""
    requires_gui: bool = False
    default_enabled: bool = True
    author: str = ""
    path: Path = field(default_factory=Path)

    @staticmethod
    def load(directory: Path) -> "PluginManifest":
        data: Dict[str, Any] = {}
        manifest_path = Path(directory) / "manifest.json"
        if manifest_path.exists():
            try:
                loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data = loaded
            except (OSError, ValueError):
                data = {}
        return PluginManifest(
            id=str(data.get("id") or Path(directory).name),
            name=str(data.get("name") or data.get("id") or Path(directory).name),
            version=str(data.get("version") or "0.0.0"),
            description=str(data.get("description") or ""),
            entry=str(data.get("entry") or "plugin.py"),
            class_name=str(data.get("class_name") or ""),
            requires_gui=bool(data.get("requires_gui") or False),
            default_enabled=bool(data.get("default_enabled", True)),
            author=str(data.get("author") or ""),
            path=Path(directory),
        )


class PluginContext:
    """插件唯一入口：日志、配置、存储、命令、事件、定时器、GUI 页面。"""

    def __init__(self, app: Any, manifest: PluginManifest) -> None:
        self.app = app
        self.manifest = manifest
        self.id = manifest.id
        self.log = get("plugin." + manifest.id)
        self.commands: CommandTable = app.commands
        self.events: EventBus = app.events
        self.scheduler: Scheduler = app.scheduler
        self._subscriptions: List[Any] = []
        self._jobs: List[str] = []

    # -- 配置 ---------------------------------------------------------------
    def config(self, key: str = "", default: Any = None) -> Any:
        section = self.app.config.section(self.id)
        if not key:
            return section
        return section.get(key, default)

    # -- 存储 ---------------------------------------------------------------
    @property
    def state_dir(self) -> Path:
        path = self.app.plugin_state_dir(self.id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def store(self, name: str) -> JsonStore:
        return JsonStore(self.state_dir / (name if name.endswith(".json") else name + ".json"))

    def log_store(self, name: str = "events") -> JsonlStore:
        return JsonlStore(self.state_dir / name)

    # -- 命令 ---------------------------------------------------------------
    def command(
        self,
        name: str,
        *,
        aliases: Iterable[str] = (),
        summary: str = "",
        usage: str = "",
        scope: str = "both",
        owner_only: bool = False,
        hidden: bool = False,
        order: int = 100,
    ):
        return self.commands.command(
            name,
            aliases=tuple(aliases),
            summary=summary,
            usage=usage,
            scope=scope,
            owner_only=owner_only,
            hidden=hidden,
            plugin=self.id,
            order=order,
        )

    # -- 事件 ---------------------------------------------------------------
    def on(self, event: str, handler, *, priority: int = 0) -> Any:
        subscription = self.events.on(event, handler, plugin=self.id, priority=priority)
        self._subscriptions.append(subscription)
        return subscription

    # -- 定时 ---------------------------------------------------------------
    def every(self, name: str, interval: float, handler, *, run_immediately: bool = False) -> Any:
        job = self.scheduler.every(
            self.id + ":" + name,
            interval,
            handler,
            plugin=self.id,
            run_immediately=run_immediately,
        )
        self._jobs.append(job.name)
        return job

    # -- GUI ---------------------------------------------------------------
    def page(self, key: str, title: str, render) -> None:
        """注册一个面板页（GUI 版本才有；非 GUI 下是空操作）。"""
        gui = getattr(self.app, "gui", None)
        if gui is None:
            return
        gui.register_page(key, title, render, plugin=self.id)

    def card(self, key: str, render) -> None:
        gui = getattr(self.app, "gui", None)
        if gui is None:
            return
        gui.register_card(key, render, plugin=self.id)

    # -- 生命周期 -----------------------------------------------------------
    def _cleanup(self) -> None:
        for subscription in self._subscriptions:
            self.events.off(subscription)
        self._subscriptions.clear()
        for name in self._jobs:
            self.scheduler.cancel(name)
        self._jobs.clear()
        self.commands.unregister_plugin(self.id)
        gui = getattr(self.app, "gui", None)
        if gui is not None:
            gui.unregister_plugin(self.id)


class Plugin:
    """插件基类：覆盖 setup/teardown 即可，其余全部可选。"""

    id: str = ""
    name: str = ""
    version: str = "0.0.0"
    description: str = ""

    def __init__(self) -> None:
        self.ctx: Optional[PluginContext] = None

    # -- 生命周期 -----------------------------------------------------------
    async def setup(self, ctx: PluginContext) -> None:  # noqa: D401 - 子类覆盖
        """注册命令/订阅事件/启动定时器。"""

    async def teardown(self) -> None:
        """释放外部资源（进程、连接）。表格与订阅由框架统一摘除。"""

    # -- 便捷 ---------------------------------------------------------------
    @property
    def state(self) -> Dict[str, Any]:
        return getattr(self, "_state", {}) or {}

    def fail(self, message: str) -> None:
        from framework.commands import CommandError

        raise CommandError(message)


class PluginManager:
    """发现、加载、启用、禁用、热重载插件。"""

    def __init__(self, app: Any, plugins_dir: Path) -> None:
        self.app = app
        self.plugins_dir = Path(plugins_dir)
        self.manifests: Dict[str, PluginManifest] = {}
        self.loaded: Dict[str, Plugin] = {}
        self.contexts: Dict[str, PluginContext] = {}

    # -- 发现 ---------------------------------------------------------------
    def discover(self) -> Dict[str, PluginManifest]:
        found: Dict[str, PluginManifest] = {}
        if not self.plugins_dir.is_dir():
            log.warning("plugins dir missing: %s", self.plugins_dir)
            return found
        for entry in sorted(self.plugins_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith(("_", ".")):
                continue
            manifest = PluginManifest.load(entry)
            found[manifest.id] = manifest
        self.manifests = found
        return found

    # -- 加载 ---------------------------------------------------------------
    def _import(self, manifest: PluginManifest):
        module_name = "fap_plugin_" + manifest.id.replace("-", "_")
        if module_name in sys.modules:
            del sys.modules[module_name]
        entry_path = manifest.path / manifest.entry
        if not entry_path.exists():
            raise FileNotFoundError("plugin entry missing: " + str(entry_path))
        spec = importlib.util.spec_from_file_location(module_name, entry_path)
        if spec is None or spec.loader is None:
            raise ImportError("cannot load " + str(entry_path))
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    def _pick_class(self, module: Any, manifest: PluginManifest):
        if manifest.class_name:
            return getattr(module, manifest.class_name)
        candidates = [
            value
            for value in vars(module).values()
            if isinstance(value, type) and issubclass(value, Plugin) and value is not Plugin
        ]
        if not candidates:
            raise ImportError("no Plugin subclass in " + manifest.id)
        return candidates[0]

    async def load(self, plugin_id: str) -> Plugin:
        manifest = self.manifests.get(plugin_id) or PluginManifest.load(self.plugins_dir / plugin_id)
        self.manifests[plugin_id] = manifest
        if manifest.requires_gui and getattr(self.app, "gui", None) is None:
            log.warning("plugin %s requires GUI; skipped in headless mode", plugin_id)
            return None
        module = self._import(manifest)
        plugin_class = self._pick_class(module, manifest)
        plugin = plugin_class()
        context = PluginContext(self.app, manifest)
        plugin.ctx = context
        await plugin.setup(context)
        self.loaded[manifest.id] = plugin
        self.contexts[manifest.id] = context
        log.info("plugin loaded: %s v%s (%s)", manifest.id, manifest.version, manifest.name)
        return plugin

    async def load_all(self, enabled: Optional[Iterable[str]] = None) -> List[str]:
        wanted = set(enabled or ())
        loaded: List[str] = []
        for plugin_id, manifest in self.discover().items():
            if wanted and plugin_id not in wanted:
                continue
            if not manifest.default_enabled and plugin_id not in wanted:
                continue
            try:
                plugin = await self.load(plugin_id)
                if plugin is not None:
                    loaded.append(plugin_id)
            except Exception as error:  # noqa: BLE001 - 一个插件坏掉不能拖垮整机
                log.exception("plugin %s failed to load: %s", plugin_id, error)
        return loaded

    async def unload(self, plugin_id: str) -> None:
        plugin = self.loaded.pop(plugin_id, None)
        context = self.contexts.pop(plugin_id, None)
        if plugin is not None:
            try:
                await plugin.teardown()
            except Exception as error:  # noqa: BLE001
                log.exception("plugin %s teardown failed: %s", plugin_id, error)
        if context is not None:
            context._cleanup()
        log.info("plugin unloaded: %s", plugin_id)

    async def reload(self, plugin_id: str) -> bool:
        was_loaded = plugin_id in self.loaded
        if was_loaded:
            await self.unload(plugin_id)
        await self.load(plugin_id)
        return True

    async def unload_all(self) -> None:
        for plugin_id in list(self.loaded.keys()):
            await self.unload(plugin_id)

    def status(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for plugin_id, manifest in self.discover().items():
            rows.append(
                {
                    "id": manifest.id,
                    "name": manifest.name,
                    "version": manifest.version,
                    "description": manifest.description,
                    "loaded": plugin_id in self.loaded,
                    "requires_gui": manifest.requires_gui,
                    "commands": len([c for c in self.app.commands.unique() if c.plugin == manifest.id]),
                }
            )
        return rows
