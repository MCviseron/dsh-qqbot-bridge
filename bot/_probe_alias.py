import asyncio, sys, time
sys.path.insert(0, '.')
import test_group_alias as T
from main import Chatter

async def main():
    bot = T.make_bot()
    bot._register(T.CONV, "group", T.GROUP, "M1")
    print("aliases:", repr(bot._alias_list()))
    print("addresses_bot:", bot.addresses_bot("群友A: 大肥鱼在吗"))
    bot.chatter[T.CONV] = Chatter(lines=["群友A: 大肥鱼在吗"], first_at=time.time(), last_judge_at=0.0)
    await bot._maybe_judge(T.CONV, force_timer=True)
    print("calls:", len(bot.bridge.calls))
    for c in bot.bridge.calls:
        print(" ->", repr(c.get("text", ""))[:120])

asyncio.run(main())
