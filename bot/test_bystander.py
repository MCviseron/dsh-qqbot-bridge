"""Judge prompt must tell the model whether it is a bystander or the addressee."""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path('.').resolve()))
import test_group_alias as T  # noqa: E402
from main import Chatter  # noqa: E402


def check(name, ok, extra=""):
    print(("ok   " if ok else "FAIL ") + name + (f" {extra}" if extra else ""))
    return 0 if ok else 1


async def prompt_for(lines):
    bot = T.make_bot()
    bot._register(T.CONV, "group", T.GROUP, "M1")
    bot.chatter[T.CONV] = Chatter(lines=list(lines), first_at=time.time(), last_judge_at=0.0)
    await bot._maybe_judge(T.CONV, force_timer=True)
    return bot.bridge.calls[-1]["text"] if bot.bridge.calls else ""


async def main():
    failures = 0

    two_people = await prompt_for(["群友B0001: 好无聊啊", "群友A0002: 那我们去玩游戏吧"])
    failures += check("两人对话 -> 标注旁观者",
                      "旁观者" in two_people and "群友A0002" in two_people, two_people[:60])
    failures += check("两人对话时禁止抢话", "不要替他们接话" in two_people)
    failures += check("保留原格式与判断段", "像群里的一员那样判断：" in two_people)

    called = await prompt_for(["群友B0001: 好无聊啊", "群友A0002: 大肥鱼你觉得呢"])
    failures += check("最后一句叫名字 -> 跳过判断直接作答",
                      "【群聊插话判断】" not in called and "大肥鱼你觉得呢" in called, called[:60])

    solo = await prompt_for(["群友B0001: 今天好热"])
    failures += check("单人独白 -> 标注没点名你", "没有点名你" in solo, solo[:60])

    print("ALL PASS" if failures == 0 else f"{failures} FAILED")
    return 0 if failures == 0 else 1


sys.exit(asyncio.run(main()))
