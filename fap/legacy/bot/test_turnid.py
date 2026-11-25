"""Turn-id based dedupe: a streamed turn must not eat the next answer."""
import os as _os, tempfile as _tempfile
_os.environ.setdefault("DSH_QQBOT_STATE_DIR", _tempfile.mkdtemp(prefix="qqbot-test-"))
import asyncio, dataclasses, sys
from pathlib import Path
sys.path.insert(0, str(Path('.').resolve()))
from main import DSHBot, load_config


class StubAPI:
    def __init__(self): self.posts = []
    async def post_c2c_message(self, **kw): self.posts.append(kw); return {"id": "m"}


class StubBridge:
    def __init__(self): self.calls = []
    async def inbound(self, **kw): self.calls.append(kw); return {"ok": True}
    async def pull(self, cursor, wait): return {"cursor": 0, "events": []}
    async def approve(self, *a, **k): return {"ok": True}


def make():
    config = dataclasses.replace(load_config(), ack_delay_s=0)
    bot = DSHBot.__new__(DSHBot)
    bot.config = config; bot.api = StubAPI(); bot.bridge = StubBridge()
    bot.state = type("S", (), {"owner_openid": "OWNER", "group_owners": {}, "save": lambda self: None})()
    bot.pool = {}
    bot._chat_turns = {}
    bot.member_index = {}
    bot.pool_idx = {}
    bot._pending_quotes = {}
    bot.owner_openid = "OWNER"
    for name, value in dict(targets={}, pending_approvals={}, pending={}, queued={}, chatter={}, recent_images={},
                            group_state={}, chime={}, _seen_ids={}, _submitted_at={}, _inflight={}, _inflight_at={},
                            _rate={}, _addressed_at={}, _bot_spoke_at={}, _last_sent={}, _last_bot_say={}, _streams={},
                            _acks={}, _msg_seq=0, _pull_task=None, _watchdog_task=None, rt=None).items():
        setattr(bot, name, value)
    bot._suppress_reply = set()
    bot._streamed_turns = {}
    bot._urgent_tasks = set()
    bot._in_quiet_hours = lambda: False
    return bot


async def main():
    failures = 0
    conv = "c2c:OWNEROPENID000000000000000000"

    bot = make(); bot._register(conv, "c2c", conv.split(":", 1)[1], None)
    bot._streamed_turns["t-1"] = 1.0
    bot._inflight[conv] = 1
    await bot._handle_event({"type": "reply", "convKey": conv, "turnId": "t-1", "text": "重复", "tools": []})
    ok = not bot.api.posts and bot._inflight.get(conv, 0) == 0 and "t-1" not in bot._streamed_turns
    print(("ok   " if ok else "FAIL ") + "同一 turnId 的耐久回复被丢弃且计数归还")
    failures += 0 if ok else 1

    bot = make(); bot._register(conv, "c2c", conv.split(":", 1)[1], None)
    bot._streamed_turns["t-1"] = 1.0
    bot._inflight[conv] = 1
    await bot._handle_event({"type": "reply", "convKey": conv, "turnId": "t-2", "text": "新的一轮", "tools": []})
    ok2 = len(bot.api.posts) == 1
    print(("ok   " if ok2 else "FAIL ") + f"新 turnId 正常发送 (posts={len(bot.api.posts)})")
    failures += 0 if ok2 else 1

    bot = make(); bot._register(conv, "c2c", conv.split(":", 1)[1], None)
    bot._streamed_turns["old"] = 1.0
    bot._inflight[conv] = 1
    bot._inflight_at[conv] = 0.0
    bot.rt = type("RT", (), {"get_float": lambda self, k, d=0.0: 0.0, "get_bool": lambda self, k, d=True: True,
                             "get_int": lambda self, k, d=0: d, "get_str": lambda self, k, d='': d})()
    bot._release_if_stuck(conv)
    ok3 = bot._inflight.get(conv, 0) == 0
    print(("ok   " if ok3 else "FAIL ") + "卡死回合会被释放（不再永久闭嘴）")
    failures += 0 if ok3 else 1

    print("ALL PASS" if failures == 0 else f"{failures} FAILED")
    return 0 if failures == 0 else 1


sys.exit(asyncio.run(main()))
