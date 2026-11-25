"""Offline check: queued messages are drained and the in-flight counter never leaks."""
import os as _os, tempfile as _tempfile
_os.environ.setdefault("DSH_QQBOT_STATE_DIR", _tempfile.mkdtemp(prefix="qqbot-test-"))
import asyncio, dataclasses, sys
from pathlib import Path
sys.path.insert(0, str(Path('.').resolve()))
from main import DSHBot, QueuedPrompt, load_config


class StubAPI:
    def __init__(self): self.posts = []
    async def post_c2c_message(self, **kw): self.posts.append(kw); return {"id": "m"}
    async def post_group_message(self, **kw): self.posts.append(kw); return {"id": "m"}


class StubBridge:
    def __init__(self): self.calls = []
    async def inbound(self, **kw): self.calls.append(kw); return {"ok": True}
    async def pull(self, cursor, wait): return {"cursor": 0, "events": []}


def make():
    config = dataclasses.replace(load_config(), ack_delay_s=0)
    bot = DSHBot.__new__(DSHBot)
    bot.config = config
    bot.api = StubAPI()
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
    bot._pending_quotes = {}
    bot._chat_turns = {}
    bot.member_index = {}
    bot._acks = {}
    bot._msg_seq = 0
    bot._pull_task = None
    bot._watchdog_task = None
    bot._urgent_tasks = set()
    bot.rt = None
    bot._in_quiet_hours = lambda: False
    return bot


async def main():
    failures = 0
    conv = "c2c:OWNEROPENID000000000000000000"

    bot = make()
    bot._register(conv, "c2c", conv.split(":", 1)[1], None)
    bot._inflight[conv] = 1
    bot._suppress_reply.add(conv)
    await bot._handle_event({"type": "reply", "convKey": conv, "text": "流式已发过", "tools": []})
    ok = bot._inflight.get(conv, 0) == 0 and conv not in bot._suppress_reply
    print(("ok   " if ok else "FAIL ") + f"流式后抑制耐久回复也归还计数 (inflight={bot._inflight.get(conv, 0)})")
    failures += 0 if ok else 1

    bot = make()
    bot._register(conv, "c2c", conv.split(":", 1)[1], None)
    bot._inflight[conv] = 1
    bot.queued[conv] = QueuedPrompt(parts=["不想动脑", "你怎么死了"], images=[], sender_name="主人", is_owner=True, chime=False, first_at=__import__("time").time())
    await bot._handle_event({"type": "reply", "convKey": conv, "text": "先回答上一句", "tools": []})
    ok2 = bool(bot.bridge.calls) and "不想动脑" in str(bot.bridge.calls[-1])
    print(("ok   " if ok2 else "FAIL ") + f"回合结束后把排队消息发出去 (inbound={len(bot.bridge.calls)})")
    failures += 0 if ok2 else 1

    ok3 = conv not in bot.queued
    print(("ok   " if ok3 else "FAIL ") + "队列已清空")
    failures += 0 if ok3 else 1

    print("ALL PASS" if failures == 0 else f"{failures} FAILED")
    return 0 if failures == 0 else 1


sys.exit(asyncio.run(main()))
