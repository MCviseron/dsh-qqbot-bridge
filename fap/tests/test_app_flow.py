"""端到端（离线）：从 on_message 到命令执行、插件存储与被动成长。

不连 QQ、不装 SDK：把 bot.send 换成收集器，直接喂 Message。
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from framework.app import FapApp
from framework.types import Message, Sender, Target

ROOT = Path(__file__).resolve().parents[1]


def message(text: str, *, openid: str = "USER1", group: bool = True) -> Message:
    kind = "group" if group else "c2c"
    conv = kind + ":GROUP1"
    return Message(
        id="M-" + str(abs(hash((text, openid))) % 10**8),
        kind=kind,
        conv_key=conv,
        sender=Sender(openid=openid, nickname="测试员", is_owner=False),
        text=text,
        target=Target(kind=kind, openid="GROUP1", conv_key=conv),
    )


class AppFlowTest(unittest.TestCase):
    def _app(self, folder: str) -> FapApp:
        app = FapApp(root=Path(folder), log_to_file=False)
        app.plugins.plugins_dir = ROOT / "plugins"
        sent = []

        async def fake_send(target, text, **kwargs):
            sent.append(text)
            return None

        app.bot = SimpleNamespace(send=fake_send, start_background=lambda: None)
        app.sent = sent
        return app

    def test_pet_game_flow(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(folder)

            async def scenario():
                await app.start(connect=False)
                await app.on_message(message("/领养 小肥鱼"))
                await app.on_message(message("/宠物"))
                await app.on_message(message("/喂食"))
                await app.on_message(message("/喂食"))          # 冷却内，应当被拒
                await app.on_message(message("今天天气不错"))    # 闲聊 -> 被动成长
                await app.on_message(message("/排行"))
                data = app.plugins.loaded["pet_game"].pets()
                await app.stop()
                return data

            data = asyncio.run(scenario())
            conv = "group:GROUP1"
            self.assertIn(conv, data)
            pet = data[conv]["USER1"]
            self.assertEqual(pet["name"], "小肥鱼")
            self.assertEqual(pet["feeds"], 1)                  # 第二次喂食被冷却挡住
            self.assertGreaterEqual(pet["coins"], 1)           # 闲聊赚到金币
            self.assertGreaterEqual(pet["exp"], 9)             # 喂食 8 + 聊天 1
            joined = "\n".join(app.sent)
            self.assertIn("领养成功", joined)
            self.assertIn("小肥鱼", joined)
            self.assertIn("秒后再喂", joined)
            self.assertIn("养成排行", joined)

    def test_framework_commands(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(folder)

            async def scenario():
                await app.start(connect=False)
                await app.on_message(message("/ping"))
                await app.on_message(message("/plugins"))
                await app.on_message(message("/help"))
                await app.on_message(message("/不存在"))
                await app.stop()

            asyncio.run(scenario())
            joined = "\n".join(app.sent)
            self.assertIn("pong", joined)
            self.assertIn("dsh_bridge", joined)
            self.assertIn("pet_game", joined)
            self.assertIn("/领养", joined)     # help 里能看到插件命令

    def test_rate_limits_and_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(folder)

            async def scenario():
                await app.start(connect=False)
                await app.on_message(message("/reload pet_game"))   # owner_only
                await app.stop()

            asyncio.run(scenario())
            self.assertIn("这条命令只有主人能用。", app.sent)


if __name__ == "__main__":
    unittest.main()
