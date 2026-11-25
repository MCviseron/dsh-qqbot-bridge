"""命令表：所有指令都注册成一条 Command，派发走表，不写 if/elif 森林。

一条命令 = 名字 + 处理函数 + 元数据（别名、用法、权限、适用范围、所属插件）。
插件在 setup 时注册，卸载时由 PluginManager 按 plugin id 整批摘除。
"""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from framework.types import Message


class CommandError(Exception):
    """命令层面的可读错误（会回给用户，不会打栈）。"""


@dataclass
class CommandContext:
    """一次命令调用的上下文。"""

    app: Any
    message: Message
    command: "Command"
    args: List[str]
    raw_args: str

    # -- 便捷访问 -----------------------------------------------------------
    @property
    def sender(self) -> Any:
        return self.message.sender

    @property
    def conv_key(self) -> str:
        return self.message.conv_key

    @property
    def is_owner(self) -> bool:
        return bool(self.message.sender.is_owner)

    @property
    def config(self) -> Any:
        return self.app.config

    def plugin_config(self) -> Dict[str, Any]:
        return self.app.config.section(self.command.plugin)

    async def say(self, text: str) -> None:
        await self.app.send(self.message.target, str(text))

    async def reply(self, text: str) -> None:
        await self.say(text)

    @property
    def storage_dir(self):
        return self.app.plugin_state_dir(self.command.plugin)

    def fail(self, message: str) -> None:
        """抛一个可读错误：由派发器回给用户，不算崩溃。"""
        raise CommandError(str(message))


@dataclass(frozen=True)
class Command:
    name: str
    handler: Callable[[CommandContext], Awaitable[Any]]
    aliases: Tuple[str, ...] = ()
    summary: str = ""
    usage: str = ""
    scope: str = "both"          # both | group | c2c
    owner_only: bool = False
    hidden: bool = False
    plugin: str = ""
    order: int = 100

    def matches(self, word: str) -> bool:
        target = word.lower()
        return target == self.name.lower() or target in {alias.lower() for alias in self.aliases}

    def help_line(self, prefix: str = "/") -> str:
        head = prefix + self.name + ((" " + self.usage) if self.usage else "")
        return head + ((" — " + self.summary) if self.summary else "")


_TOKEN_RE = re.compile(r"\s+")
_LEAD_MENTION_RE = re.compile(r"^(?:@\S+\s+)+")


class CommandTable:
    """命令注册表 + 派发器。"""

    def __init__(self, prefix: str = "/") -> None:
        self.prefix = prefix or "/"
        self._commands: Dict[str, Command] = {}
        self._order: List[str] = []

    # -- 注册 ---------------------------------------------------------------
    def register(self, command: Command) -> Command:
        key = command.name.lower()
        if key in self._commands:
            raise ValueError("duplicate command: " + command.name)
        for alias in command.aliases:
            if alias.lower() in self._commands:
                raise ValueError("alias already taken: " + alias)
        self._commands[key] = command
        for alias in command.aliases:
            self._commands[alias.lower()] = command
        self._order.append(key)
        return command

    def command(
        self,
        name: str,
        *,
        aliases: Sequence[str] = (),
        summary: str = "",
        usage: str = "",
        scope: str = "both",
        owner_only: bool = False,
        hidden: bool = False,
        plugin: str = "",
        order: int = 100,
    ) -> Callable[[Callable[[CommandContext], Awaitable[Any]]], Callable[[CommandContext], Awaitable[Any]]]:
        """装饰器写法：@table.command("ping", summary="测活")"""

        def wrapper(handler: Callable[[CommandContext], Awaitable[Any]]):
            self.register(
                Command(
                    name=name,
                    handler=handler,
                    aliases=tuple(aliases),
                    summary=summary,
                    usage=usage,
                    scope=scope,
                    owner_only=owner_only,
                    hidden=hidden,
                    plugin=plugin,
                    order=order,
                )
            )
            return handler

        return wrapper

    def unregister_plugin(self, plugin_id: str) -> int:
        removed = 0
        for key, command in list(self._commands.items()):
            if command.plugin == plugin_id:
                del self._commands[key]
                removed += 1
        self._order = [name for name in self._order if name in self._commands]
        return removed

    # -- 查询 ---------------------------------------------------------------
    def unique(self) -> List[Command]:
        seen: Dict[int, Command] = {}
        for name in self._order:
            command = self._commands.get(name)
            if command is not None:
                seen[id(command)] = command
        return sorted(seen.values(), key=lambda item: (item.order, item.name))

    def find(self, word: str) -> Optional[Command]:
        return self._commands.get(str(word).lower())

    def resolve(self, text: str) -> Optional[Tuple[Command, List[str], str]]:
        """把一段文本解析成 (命令, 参数, 原始参数字符串)；不是命令返回 None。"""
        stripped = str(text or "").strip()
        # 群里必须先 @机器人：「@蓝色大肥鱼 /ping」里的命令在第二段
        stripped = _LEAD_MENTION_RE.sub("", stripped)
        if not stripped.startswith(self.prefix):
            return None
        body = stripped[len(self.prefix):].strip()
        if not body:
            return None
        parts = _TOKEN_RE.split(body)
        name = parts[0]
        command = self.find(name)
        if command is None:
            return None
        rest = parts[1:]
        raw = body[len(name):].strip()
        return command, rest, raw

    def help_text(self, *, scope: str = "both", is_owner: bool = False, plugin: str = "") -> str:
        """按插件分组输出；同一插件的命令一定连在一起（不受 order 影响）。"""
        groups: Dict[str, List[Command]] = {}
        for command in self.unique():
            if command.hidden:
                continue
            if plugin and command.plugin != plugin:
                continue
            if command.scope not in ("both", scope):
                continue
            if command.owner_only and not is_owner:
                continue
            groups.setdefault(command.plugin, []).append(command)
        blocks: List[str] = []
        for plugin_id, commands in groups.items():
            title = plugin_id or "框架"
            body = "\n".join("  " + item.help_line(self.prefix) for item in commands)
            blocks.append("【" + title + "】\n" + body)
        return "\n\n".join(blocks) or "（没有可用的命令）"

    # -- 派发 ---------------------------------------------------------------
    async def dispatch(self, app: Any, message: Message) -> Any:
        resolved = self.resolve(message.text)
        if resolved is None:
            return None
        command, args, raw = resolved
        if command.scope == "group" and not message.is_group:
            await app.send(message.target, "这条命令只能在群里用。")
            return None
        if command.scope == "c2c" and message.is_group:
            await app.send(message.target, "这条命令只能在私聊用。")
            return None
        if command.owner_only and not message.sender.is_owner:
            await app.send(message.target, "这条命令只有主人能用。")
            return None
        context = CommandContext(app=app, message=message, command=command, args=args, raw_args=raw)
        try:
            result = command.handler(context)
            if inspect.isawaitable(result):
                result = await result
        except CommandError as error:
            await app.send(message.target, str(error))
        except Exception as error:  # noqa: BLE001 - 单个命令炸掉不能拖垮框架
            app.logger.exception("command %s failed: %s", command.name, error)
            await app.send(message.target, "命令执行出错：" + type(error).__name__)
        # 命中即算处理过（处理函数多半没有返回值）
        return True


def split_args(raw: str) -> List[str]:
    return [part for part in _TOKEN_RE.split(str(raw or "").strip()) if part]


def parse_kv(args: Iterable[str]) -> Dict[str, str]:
    """把 --key=value 之类解析成字典（给可选参数用）。"""
    out: Dict[str, str] = {}
    for item in args:
        if item.startswith("--") and "=" in item:
            key, _, value = item[2:].partition("=")
            out[key.strip()] = value.strip()
    return out
