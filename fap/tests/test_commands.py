"""命令表：解析、别名、权限、帮助、按插件整批摘除。"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

from framework.commands import CommandTable, CommandError
from framework.types import Message, Sender, Target


def make_message(text: str, *, group: bool = True, owner: bool = False) -> Message:
    kind = "group" if group else "c2c"
    conv = kind + ":CONV"
    return Message(
        id="M1",
        kind=kind,
        conv_key=conv,
        sender=Sender(openid="U1", nickname="测试", is_owner=owner),
        text=text,
        target=Target(kind=kind, openid="CONV", conv_key=conv),
    )


class FakeApp:
    def __init__(self) -> None:
        self.sent = []
        self.logger = SimpleNamespace(exception=lambda *a, **k: None, info=lambda *a, **k: None)
        self.config = SimpleNamespace(section=lambda name: {})

    async def send(self, target, text, **kwargs):
        self.sent.append(text)


class CommandTableTest(unittest.TestCase):
    def setUp(self) -> None:
        self.table = CommandTable(prefix="/")
        self.app = FakeApp()

    def test_register_and_dispatch(self) -> None:
        calls = []

        @self.table.command("ping", summary="测活")
        async def _ping(ctx):
            calls.append(ctx.raw_args)
            await ctx.say("pong")

        asyncio.run(self.table.dispatch(self.app, make_message("/ping")))
        self.assertEqual(calls, [""])
        self.assertEqual(self.app.sent, ["pong"])

    def test_alias_and_args(self) -> None:
        seen = []

        @self.table.command("喂食", aliases=("feed",))
        async def _feed(ctx):
            seen.append(ctx.args)

        asyncio.run(self.table.dispatch(self.app, make_message("/feed 一点点 加餐")))
        self.assertEqual(seen, [["一点点", "加餐"]])

    def test_command_after_at_mention(self) -> None:
        """群里必须先 @机器人，命令出现在第二段也要能命中。"""
        seen = []

        @self.table.command("ping")
        async def _ping(ctx):
            seen.append(ctx.raw_args or "no-args")

        asyncio.run(self.table.dispatch(self.app, make_message("@群友ABCDEF /ping")))
        asyncio.run(self.table.dispatch(self.app, make_message("@蓝色大肥鱼 @群友ABCDEF /ping 加餐")))
        self.assertEqual(seen, ["no-args", "加餐"])

    def test_unknown_command_returns_none(self) -> None:
        self.assertIsNone(self.table.resolve("/nope"))
        self.assertIsNone(self.table.resolve("没有斜杠"))

    def test_owner_only(self) -> None:
        @self.table.command("危险", owner_only=True)
        async def _danger(ctx):
            await ctx.say("执行")

        asyncio.run(self.table.dispatch(self.app, make_message("/危险")))
        self.assertEqual(self.app.sent, ["这条命令只有主人能用。"])

        self.app.sent.clear()
        asyncio.run(self.table.dispatch(self.app, make_message("/危险", owner=True)))
        self.assertEqual(self.app.sent, ["执行"])

    def test_scope_guard(self) -> None:
        @self.table.command("私聊专用", scope="c2c")
        async def _c2c(ctx):
            await ctx.say("ok")

        asyncio.run(self.table.dispatch(self.app, make_message("/私聊专用", group=True)))
        self.assertEqual(self.app.sent, ["这条命令只能在私聊用。"])

    def test_command_error_is_user_facing(self) -> None:
        @self.table.command("炸")
        async def _boom(ctx):
            raise CommandError("参数不对")

        asyncio.run(self.table.dispatch(self.app, make_message("/炸")))
        self.assertEqual(self.app.sent, ["参数不对"])

    def test_unregister_plugin(self) -> None:
        @self.table.command("a", plugin="p1")
        async def _a(ctx):
            return None

        @self.table.command("b", plugin="p1")
        async def _b(ctx):
            return None

        @self.table.command("c", plugin="p2")
        async def _c(ctx):
            return None

        self.assertEqual(len(self.table.unique()), 3)
        removed = self.table.unregister_plugin("p1")
        self.assertEqual(removed, 2)
        self.assertEqual([c.name for c in self.table.unique()], ["c"])

    def test_help_text_filters(self) -> None:
        @self.table.command("user-cmd", summary="用户")
        async def _u(ctx):
            return None

        @self.table.command("owner-cmd", summary="主人", owner_only=True)
        async def _o(ctx):
            return None

        plain = self.table.help_text(scope="both", is_owner=False)
        self.assertIn("user-cmd", plain)
        self.assertNotIn("owner-cmd", plain)

        admin = self.table.help_text(scope="both", is_owner=True)
        self.assertIn("owner-cmd", admin)

    def test_duplicate_rejected(self) -> None:
        self.table.register(__import__("framework.commands", fromlist=["Command"]).Command(name="x", handler=lambda ctx: None))
        with self.assertRaises(ValueError):
            self.table.register(__import__("framework.commands", fromlist=["Command"]).Command(name="x", handler=lambda ctx: None))


if __name__ == "__main__":
    unittest.main()
