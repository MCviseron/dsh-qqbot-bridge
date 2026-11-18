"""Offline check of the group routing rules (no gateway, no DSH)."""
import asyncio
import dataclasses
import sys
import time
from pathlib import Path

from viseron_qqbotpy import GroupMessage, User

sys.path.insert(0, str(Path(__file__).resolve().parent))
from main import DSHBot, load_config  # noqa: E402

BOT_MEMBER = "BOTMEMBER0000000000000000000001"
GROUP = "CCE96DDF6F462E1010E5721BBA1B6CBB"
OWNER_MEMBER = "35AD3A2431B0901EDD915A29F1AFF7F1"
MEMBER = "67BC6C00000000000000000000000099"


class StubAPI:
    def __init__(self):
        self.posts = []

    async def get_group_bot_state(self, group_openid):
        return {"member_openid": BOT_MEMBER, "recv_msg_setting": "all", "allow_proactive_msg": True}

    async def get_group_member(self, group_openid, member_openid):
        raise RuntimeError("11253")

    async def post_group_message(self, **payload):
        self.posts.append(payload)
        return {"id": "m1"}


class StubBridge:
    def __init__(self):
        self.calls = []

    async def inbound(self, **kwargs):
        self.calls.append(kwargs)
        return {}

    async def pull(self, cursor, wait_ms):
        return {"cursor": 0, "events": []}


def make_bot(owner_bound=True):
    config = dataclasses.replace(load_config(), debounce_s=0.02, debounce_max_s=0.05, ack_delay_s=0)
    bot = DSHBot.__new__(DSHBot)
    bot.config = config
    bot.api = StubAPI()
    bot.pool = {}
    bot.pool_idx = {}
    bot._pending_quotes = {}
    bot.bridge = StubBridge()
    bot.state = type("S", (), {
        "owner_openid": "OWNER",
        "group_owners": {GROUP: OWNER_MEMBER} if owner_bound else {},
        "save": lambda self: None,
    })()
    bot.owner_openid = "OWNER"
    bot.targets = {}
    bot.pending_approvals = {}
    bot.pending = {}
    bot.queued = {}
    bot.group_state = {}
    bot.chime = {}
    bot._seen_ids = {}
    bot._submitted_at = {}
    bot._inflight = {}
    bot._addressed_at = {}
    bot._bot_spoke_at = {}
    bot._last_sent = {}
    bot._last_bot_say = {}
    bot.chatter = {}
    bot.recent_images = {}
    bot._inflight_at = {}
    bot._rate = {}
    bot.rt = None
    bot._role_probe_failed_at = 0.0
    bot._msg_seq = 0
    bot._acks = {}
    bot._pull_task = None
    return bot


def msg(text, member=MEMBER, mentions=None, attachments=None):
    return GroupMessage(
        id=f"id-{time.time_ns()}",
        group_openid=GROUP,
        content=text,
        author=User(member_openid=member, user_openid="U1"),
        mentions=mentions or [],
        attachments=attachments or [],
    )


def prompts(bot):
    return [call for call in bot.bridge.calls if not call.get("context_only")]


async def case(label, bot, message, expect_prompt):
    await bot.on_group_message_create(message)
    await asyncio.sleep(0.25)
    got = bool(prompts(bot))
    ok = got == expect_prompt
    print(("ok   " if ok else "FAIL ") + label + f" (prompt={got}, expected={expect_prompt})")
    return 0 if ok else 1


async def main():
    failures = 0

    # @机器人 才算点名；@别人 不能回
    bot = make_bot()
    self_mention = msg("你在吗", mentions=[User(member_openid=BOT_MEMBER)])
    ok = await bot._mentions_bot(self_mention)
    print(("ok   " if ok else "FAIL ") + "@机器人 -> 认作点名")
    if not ok:
        failures += 1

    bot = make_bot()
    other_mention = msg("老王你看这个", mentions=[User(member_openid="99998888777766665555444433332222", username="老王")])
    ok = not await bot._mentions_bot(other_mention)
    print(("ok   " if ok else "FAIL ") + "@别人 -> 不认作点名")
    if not ok:
        failures += 1

    bot = make_bot()
    ok = not await bot._mentions_bot(msg("没有 mention"))
    print(("ok   " if ok else "FAIL ") + "没有 mention -> 不认作点名")
    if not ok:
        failures += 1


    bot = make_bot()
    failures += await case("窗口外闲聊 -> 只记上下文", bot, msg("今晚谁开黑"), False)

    bot = make_bot()
    for index in range(3):
        await bot.on_group_message_create(msg(f"闲聊第{index + 1}句"))
        await asyncio.sleep(0.15)
    ok = not prompts(bot)
    print(("ok   " if ok else "FAIL ") + f"闲聊未攒够 -> 不插话 (prompts={len(prompts(bot))})")
    if not ok:
        failures += 1

    await bot.on_group_message_create(msg("闲聊第4句：你们今晚玩啥"))
    await asyncio.sleep(0.3)
    judged = [call for call in prompts(bot) if "群聊插话判断" in str(call.get("text", ""))]
    ok = bool(judged)
    print(("ok   " if ok else "FAIL ") + f"攒够 4 条 -> 触发插话判断 (prompts={len(prompts(bot))})")
    if not ok:
        failures += 1
    first_prompt = str(judged[0].get("text", "")) if judged else ""
    ok = "没看到你在群里说过话" in first_prompt and "一直没说话" not in first_prompt
    print(("ok   " if ok else "FAIL ") + "没说过话时提示词说「还没说过」")
    if not ok:
        failures += 1

    await bot.on_group_message_create(msg("闲聊第5句"))
    await asyncio.sleep(0.3)
    ok = len(prompts(bot)) == len(judged)
    print(("ok   " if ok else "FAIL ") + "判断刚结束 -> 冷却内不再插话")
    if not ok:
        failures += 1

    bot = make_bot()
    bot._last_bot_say[f"group:{GROUP}"] = ("我刚说的话", time.time() - 30)
    bot._last_judge_free = True
    for index in range(4):
        await bot.on_group_message_create(msg(f"接话第{index + 1}句"))
        await asyncio.sleep(0.1)
    recent = [call for call in prompts(bot) if "群聊插话判断" in str(call.get("text", ""))]
    ok = bool(recent) and "最近说过" in str(recent[0].get("text", ""))
    print(("ok   " if ok else "FAIL ") + "说过话时提示词描述「最近说过」")
    if not ok:
        failures += 1

    bot = make_bot()
    bot._last_bot_say[f"group:{GROUP}"] = ("七分钟前说的话", time.time() - 400)
    for index in range(4):
        await bot.on_group_message_create(msg(f"又聊第{index + 1}句"))
        await asyncio.sleep(0.1)
    later = [call for call in prompts(bot) if "群聊插话判断" in str(call.get("text", ""))]
    body = str(later[0].get("text", "")) if later else ""
    ok = bool(later) and "安静了" in body and "最近没说话" in body
    print(("ok   " if ok else "FAIL ") + "超过记忆窗口 -> 描述为「安静了 X 分钟」")
    if not ok:
        failures += 1

    bot = make_bot()
    bot_id = User(member_openid=BOT_MEMBER)
    failures += await case("群友 @ 带文字 -> 答", bot, msg("唱首歌", mentions=[bot_id]), True)

    bot = make_bot()
    failures += await case(
        "群友 @ 只有图 -> 也答", bot, msg("", mentions=[User(member_openid=BOT_MEMBER)], attachments=[{"content_type": "image/png"}]), True
    )

    bot = make_bot()
    failures += await case("主人窗口外不抢话", bot, msg("我自己部署的", member=OWNER_MEMBER), False)

    bot = make_bot()
    bot._addressed_at[f"group:{GROUP}"] = time.time()
    failures += await case("主人紧接着说也不答（无 @）", bot, msg("那你觉得呢", member=OWNER_MEMBER), False)

    bot = make_bot()
    failures += await case("叫名字但没 @ -> 也答（别名视同点名）", bot, msg("大肥鱼你在吗"), True)

    bot = make_bot()
    await bot.on_group_message_create(msg("/状态"))
    await asyncio.sleep(0.25)
    ok = bool(bot.api.posts) and not prompts(bot)
    print(("ok   " if ok else "FAIL ") + f"/命令没 @ -> 本地直接回 (posts={len(bot.api.posts)}, prompts={len(prompts(bot))})")
    if not ok:
        failures += 1

    print("ALL PASS" if failures == 0 else f"{failures} FAILED")
    return 0 if failures == 0 else 1


sys.exit(asyncio.run(main()))
