"""Plan B: independent judge decides, main model gets the verbatim pool."""
import asyncio
import dataclasses
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path('.').resolve()))
from main import DSHBot, PooledMessage, load_config  # noqa: E402

GROUP = "CCE96DDF6F462E1010E5721BBA1B6CBB"
CONV = f"group:{GROUP}"


class _RT:
    def __init__(self, mode):
        self.mode = mode

    def get_bool(self, key, default=True):
        if key == "group_at_only":
            return False
        if key == "interject_hook_only":
            return False  # 这些用例验证的是判断提示词本身，不走省钱预筛
        return default

    def get_int(self, key, default=0):
        return 0 if key == "debounce_ms" else default

    def get_float(self, key, default=0.0):
        return default

    def get_str(self, key, default=""):
        if key == "group_mode":
            return self.mode
        return default

    def get(self, key, default=None):
        if key == "group_mode":
            return self.mode
        return default


class StubAPI:
    def __init__(self):
        self.posts = []

    async def post_group_message(self, **kw):
        self.posts.append(kw)
        return {"id": "g"}


class StubBridge:
    def __init__(self, verdict):
        self.verdict = verdict
        self.calls = []
        self.judged = []

    async def judge(self, conv_key, transcript):
        self.judged.append(transcript)
        return self.verdict

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


def make_bot(mode, verdict):
    config = dataclasses.replace(load_config(), ack_delay_s=0, debounce_s=0.0, debounce_max_s=0.0)
    bot = DSHBot.__new__(DSHBot)
    bot.config = config
    bot.api = StubAPI()
    bot.bridge = StubBridge(verdict)
    bot.state = type("S", (), {"owner_openid": "OWNER", "group_owners": {}, "save": lambda self: None})()
    bot.owner_openid = "OWNER"
    bot.rt = _RT(mode)
    for name in ("targets", "pending_approvals", "pending", "queued", "recent_images", "group_state", "chime",
                 "_seen_ids", "_submitted_at", "_inflight", "_inflight_at", "_rate", "_addressed_at",
                 "_bot_spoke_at", "_last_sent", "_last_bot_say", "_streams", "_acks", "_pending_quotes", "pool"):
        setattr(bot, name, {})
    bot.pool_idx = {}
    bot._streamed_turns = {}
    bot._chat_turns = {}
    bot.member_index = {}
    bot._suppress_reply = set()
    bot._urgent_tasks = set()
    bot._pull_task = None
    bot._watchdog_task = None
    bot.chatter = {}
    bot._msg_seq = 0
    bot._in_quiet_hours = lambda: False
    return bot


def check(name, ok, extra=""):
    print(("ok   " if ok else "FAIL ") + name + (f" {extra}" if extra else ""))
    return 0 if ok else 1


async def main():
    failures = 0

    bot = make_bot("B", {"ok": True, "needReply": False, "note": "两个人在互相聊"})
    bot._register(CONV, "group", GROUP, "M1")
    bot.pool["M0"] = PooledMessage(message_id="M0", conv_key=CONV, kind="group", openid=GROUP,
                                   author="群友A", text="好无聊啊", outbound=False, at=time.time())
    await bot.on_group_message_create(Msg("那我们去玩游戏吧"))
    await asyncio.sleep(0.2)
    failures += check("B 模式：判断为不回 -> 不打扰主模型", not bot.bridge.calls or bot.bridge.calls[-1].get("context_only") is True,
                      str(bot.bridge.calls[-1:])[:80])
    failures += check("B 模式：原文进了判断器", bool(bot.bridge.judged) and "好无聊啊" in bot.bridge.judged[-1])
    failures += check("原文带时间戳", bool(bot.bridge.judged) and bot.bridge.judged[-1].startswith("["))

    bot = make_bot("B", {"ok": True, "needReply": True, "note": "在问机器人"})
    bot._register(CONV, "group", GROUP, "M1")
    bot.pool["M0"] = PooledMessage(message_id="M0", conv_key=CONV, kind="group", openid=GROUP,
                                   author="群友A", text="好无聊啊", outbound=False, at=time.time())
    await bot.on_group_message_create(Msg("那你觉得呢"))   # 没叫名字，才走 Plan B 判断
    await asyncio.sleep(0.2)
    sent = bot.bridge.calls[-1]["text"] if bot.bridge.calls else ""
    failures += check("B 模式：判断为回 -> 带原文交给主模型", "好无聊啊" in sent, sent[:60])
    failures += check("B 模式：附上判断理由", "判断参考" in sent and "在问机器人" in sent)

    bot = make_bot("A", {"ok": True, "needReply": True, "note": ""})
    bot._register(CONV, "group", GROUP, "M1")
    bot.chatter[CONV] = type("C", (), {"lines": ["群友A: 今晚开黑"], "first_at": time.time(), "last_judge_at": 0.0})()
    await bot._maybe_judge(CONV, force_timer=True)
    sent = bot.bridge.calls[-1]["text"] if bot.bridge.calls else ""
    failures += check("A 模式保持原样（仍是插话判断提示词）", "【群聊插话判断】" in sent and not bot.bridge.judged)

    print("ALL PASS" if failures == 0 else f"{failures} FAILED")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
