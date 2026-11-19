"""Plan A routing: naming the bot in plain text must get a real answer."""
import asyncio
import dataclasses
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path('.').resolve()))
from main import DSHBot, Chatter, load_config  # noqa: E402

GROUP = "CCE96DDF6F462E1010E5721BBA1B6CBB"
CONV = f"group:{GROUP}"


class _RT:
    def get_bool(self, key, default=True):
        return default

    def get_int(self, key, default=0):
        return default

    def get_float(self, key, default=0.0):
        return default

    def get_str(self, key, default=""):
        return default

    def get(self, key, default=None):
        return default


class StubAPI:
    def __init__(self):
        self.posts = []

    async def post_group_message(self, **kw):
        self.posts.append(kw)
        return {"id": "g1"}

    async def post_c2c_message(self, **kw):
        self.posts.append(kw)
        return {"id": "c1"}

    async def get_group_bot_state(self, group_openid):
        return {"member_openid": "BOTMEMBER", "recv_msg_setting": "all", "allow_proactive_msg": True}


class StubBridge:
    def __init__(self):
        self.calls = []

    async def inbound(self, **kw):
        self.calls.append(kw)
        return {"ok": True}

    async def pull(self, cursor, wait):
        return {"cursor": 0, "events": []}


class Msg:
    def __init__(self, text, message_id="M1"):
        self.id = message_id
        self.content = text
        self.group_openid = GROUP
        self.attachments = []
        self.mentions = []
        self.raw = {}
        self.author = type("A", (), {"member_openid": "MEMBER1", "user_openid": "U1"})()


def make_bot():
    config = dataclasses.replace(load_config(), ack_delay_s=0, debounce_s=0.0, debounce_max_s=0.0)
    bot = DSHBot.__new__(DSHBot)
    bot.config = config
    bot.api = StubAPI()
    bot.bridge = StubBridge()
    bot.state = type("S", (), {"owner_openid": "OWNER", "group_owners": {}, "save": lambda self: None})()
    bot.owner_openid = "OWNER"
    bot.rt = _RT()
    for name in ("targets", "pending_approvals", "pending", "queued", "recent_images", "group_state", "chime",
                 "_seen_ids", "_submitted_at", "_inflight", "_inflight_at", "_rate", "_addressed_at",
                 "_bot_spoke_at", "_last_sent", "_last_bot_say", "_streams", "_acks", "_pending_quotes", "pool"):
        setattr(bot, name, {})
    bot.pool_idx = {}
    bot._streamed_turns = {}
    bot._chat_turns = {}
    bot._suppress_reply = set()
    bot._urgent_tasks = set()
    bot._pull_task = None
    bot._watchdog_task = None
    bot.chatter = {}
    bot._msg_seq = 0
    return bot


def check(name, ok, extra=""):
    print(("ok   " if ok else "FAIL ") + name + (f" {extra}" if extra else ""))
    return 0 if ok else 1


async def main():
    failures = 0

    bot = make_bot()
    bot._register(CONV, "group", GROUP, "M1")
    await bot.on_group_message_create(Msg("大肥鱼 你看看这个"))
    await asyncio.sleep(0.2)
    sent = bot.bridge.calls[-1]["text"] if bot.bridge.calls else ""
    failures += check("正文里叫名字 -> 直接进工作模式", bool(sent) and "【群聊插话判断】" not in sent, sent[:40])

    bot = make_bot()
    bot._register(CONV, "group", GROUP, "M1")
    bot.chatter[CONV] = Chatter(lines=["群友A: 大肥鱼在吗"], first_at=time.time(), last_judge_at=0.0)
    await bot._maybe_judge(CONV, force_timer=True)
    sent = bot.bridge.calls[-1]["text"] if bot.bridge.calls else ""
    failures += check("缓冲里叫名字 -> 跳过判断直接答", bool(sent) and "【群聊插话判断】" not in sent, sent[:40])

    bot = make_bot()
    bot._register(CONV, "group", GROUP, "M1")
    bot.chatter[CONV] = Chatter(lines=["群友A: 今晚开黑"], first_at=time.time(), last_judge_at=0.0)
    await bot._maybe_judge(CONV, force_timer=True)
    sent = bot.bridge.calls[-1]["text"] if bot.bridge.calls else ""
    failures += check("普通闲聊 -> 仍走插话判断", "【群聊插话判断】" in sent, sent[:40])

    bot = make_bot()
    bot._register(CONV, "group", GROUP, "M1")
    bot.chatter[CONV] = Chatter(lines=["群友A: 今晚开黑"], first_at=time.time(), last_judge_at=0.0)
    await bot._maybe_judge(CONV, force_timer=True)
    sent = bot.bridge.calls[-1]["text"] if bot.bridge.calls else ""
    failures += check("判断提示词给出说话对象并留出口", "最后一句来自" in sent and "NO_REPLY" in sent, "")

    print("ALL PASS" if failures == 0 else f"{failures} FAILED")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
