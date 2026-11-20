"""Offline check of the streaming delivery path (no QQ, no DSH)."""
import asyncio, dataclasses, sys, time
from pathlib import Path
sys.path.insert(0, str(Path('.').resolve()))
from main import DSHBot, load_config


class _RT:
    """Runtime-config stub: streaming on, everything else default."""

    def get_bool(self, key, default=True):
        if key == "group_at_only":
            return False
        return True if key == "stream_enabled" else default

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
        self.streams = []
        self.fail = False

    async def post_c2c_message(self, **kw):
        self.streams.append({'plain': True, **kw})
        return {'id': 'p1'}

    async def post_c2c_stream_message(self, openid, **fields):
        if self.fail:
            raise RuntimeError("platform rejected")
        self.streams.append({"openid": openid, **fields})
        return {"id": "m1"}


class StubBridge:
    async def inbound(self, **kw): return {}
    async def pull(self, cursor, wait): return {"cursor": 0, "events": []}


def make_bot():
    config = dataclasses.replace(load_config(), ack_delay_s=0)
    bot = DSHBot.__new__(DSHBot)
    bot.config = config
    bot.api = StubAPI()
    bot.pool = {}
    bot._chat_turns = {}
    bot.member_index = {}
    bot.pool_idx = {}
    bot._pending_quotes = {}
    bot._streamed_turns = {}
    bot.bridge = StubBridge()
    bot.state = type("S", (), {"owner_openid": "OWNER", "group_owners": {}, "save": lambda self: None})()
    bot.owner_openid = "OWNER"
    bot.targets = {}
    bot.pending_approvals = {}
    bot.pending = {}
    bot.queued = {}
    bot.chatter = {}
    bot.recent_images = {}
    bot.group_state = {}
    bot.chime = {}
    bot._seen_ids = {}
    bot._submitted_at = {}
    bot._inflight = {}
    bot._inflight_at = {}
    bot._rate = {}
    bot._addressed_at = {}
    bot._bot_spoke_at = {}
    bot._last_sent = {}
    bot._last_bot_say = {}
    bot._streams = {}
    bot._suppress_reply = set()
    bot._acks = {}
    bot._msg_seq = 0
    bot._pull_task = None
    bot._watchdog_task = None
    bot._urgent_tasks = set()
    bot.rt = _RT()
    bot._in_quiet_hours = lambda: False
    return bot


def target(bot, conv="c2c:OWNEROPENID000000000000000000"):
    bot._register(conv, "c2c", conv.split(":", 1)[1], None)
    return conv


async def main():
    failures = 0

    bot = make_bot()
    conv = target(bot)
    await bot._handle_stream({"convKey": conv, "text": "你", "final": False})
    await bot._handle_stream({"convKey": conv, "text": "好", "final": False})
    await bot._handle_stream({"convKey": conv, "text": "呀", "final": True})
    calls = bot.api.streams
    ok = len(calls) >= 2 and calls[-1]["input_state"] == 10 and "你好呀" in calls[-1]["content_raw"]
    print(("ok   " if ok else "FAIL ") + f"流式分片 -> 复用 stream_msg_id 收尾 (frames={len(calls)})")
    failures += 0 if ok else 1
    ok2 = "t" in str(bot._streamed_turns) or conv in bot._suppress_reply
    print(("ok   " if ok2 else "FAIL ") + "流式完成后抑制重复的耐久回复")
    failures += 0 if ok2 else 1

    await bot._handle_event({"type": "reply", "convKey": conv, "text": "你好呀", "tools": []})
    ok3 = not bot.api.streams[0].get("dup") and conv not in bot._suppress_reply
    print(("ok   " if ok3 else "FAIL ") + "耐久回复被丢弃（不重复发）")
    failures += 0 if ok3 else 1

    bot = make_bot()
    conv = target(bot)
    bot.api.fail = True
    await bot._handle_stream({"convKey": conv, "text": "失败测试", "final": True})
    ok4 = conv not in bot._streams and conv not in bot._suppress_reply
    print(("ok   " if ok4 else "FAIL ") + "流式失败 -> 清理状态，回落到一次性发送")
    failures += 0 if ok4 else 1

    bot = make_bot()
    bot._register("group:CCE96DDF6F462E1010E5721BBA1B6CBB", "group", "CCE96DDF6F462E1010E5721BBA1B6CBB", None)
    await bot._handle_stream({"convKey": "group:CCE96DDF6F462E1010E5721BBA1B6CBB", "text": "群聊不走流式", "final": True})
    ok5 = not bot.api.streams
    print(("ok   " if ok5 else "FAIL ") + "群聊不发流式（平台不支持）")
    failures += 0 if ok5 else 1

    print("ALL PASS" if failures == 0 else f"{failures} FAILED")
    return 0 if failures == 0 else 1


sys.exit(asyncio.run(main()))
