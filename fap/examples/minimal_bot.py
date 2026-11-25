"""最小示例：用框架跑一个只回 /ping 的机器人（不需要任何插件）。

    python examples/minimal_bot.py        # 需要 config.json 里有 appid/appsecret

框架的用法就这么点：造 FapApp → 注册命令（或加载插件）→ run()。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from framework import FapApp  # noqa: E402


def build() -> FapApp:
    app = FapApp(root=ROOT)

    # 也可以不写插件，直接在 app.commands 上挂命令（适合一次性脚本）
    @app.commands.command("hi", summary="最小示例的招呼")
    async def _hi(context) -> None:
        await context.say("hi，" + context.sender.display)

    return app


if __name__ == "__main__":
    build().run()
