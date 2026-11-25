"""Offline check of the command paths in main.py (no gateway, no DSH)."""
import os as _os, tempfile as _tempfile
_os.environ.setdefault("DSH_QQBOT_STATE_DIR", _tempfile.mkdtemp(prefix="qqbot-test-"))
import asyncio
import sys
from pathlib import Path

from viseron_qqbotpy import GroupMessage, User

sys.path.insert(0, str(Path(__file__).resolve().parent))
from main import DSHBot, load_config  # noqa: E402


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
        self.posts = []
        self.links = 0

    async def get_group_bot_state(self, group_openid):
        return {
            "member_openid": "BOTMEMBER",
            "joined_at": "2026-10-29T01:47:32+08:00",
            "recv_msg_setting": "all",
            "allow_proactive_msg": True,
            "member_role": "member",
        }

    async def get_group_member(self, group_openid, member_openid):
        raise RuntimeError("11253 capability not opened")

    async def create_url_link(self, callback_data=None, **kwargs):
        self.links += 1
        return {"data": {"url": "https://bot.q.qq.com/s/TESTLINK"}}

    async def post_group_message(self, **payload):
        self.posts.append(payload)
        return {"id": "m1"}


def make_bot():
    config = load_config()
    bot = DSHBot(intents=None, config=config) if False else DSHBot.__new__(DSHBot)
    bot.config = config
    bot.api = StubAPI()
    bot.pool = {}
    bot._chat_turns = {}
    bot.member_index = {}
    bot.pool_idx = {}
    bot._pending_quotes = {}
    bot.rt = _RT()
    bot._suppress_reply = set()
    bot._seen_ids = {}
    bot._streamed_turns = {}
    bot._streams = {}
    bot._urgent_tasks = {}
    bot._inflight = {}
    bot._inflight_at = {}
    bot._rate = {}
    bot._submitted_at = {}
    bot._bot_spoke_at = {}
    bot._last_sent = {}
    bot._last_bot_say = {}
    bot._addressed_at = {}
    bot.recent_images = {}
    bot.chatter = {}
    bot.queued = {}
    bot.messages_owner = {}
    bot._watchdog_task = None
    bot.state = type("S", (), {
        "owner_openid": "OWNER",
        "group_owners": {"CCE96DDF6F462E1010E5721BBA1B6CBB": "35AD3A2431B0901EDD915A29F1AFF7F1"},
        "save": lambda self: None,
    })()
    bot.owner_openid = "OWNER"
    bot.targets = {}
    bot.pending_approvals = {}
    bot.pending = {}
    bot.group_state = {}
    bot.chime = {}
    bot._msg_seq = 0
    bot._acks = {}
    bot._pull_task = None
    bot._in_quiet_hours = lambda: False
    return bot


def group_message(text, member="35AD3A2431B0901EDD915A29F1AFF7F1"):
    return GroupMessage(
        id="msg1",
        group_openid="CCE96DDF6F462E1010E5721BBA1B6CBB",
        content=text,
        author=User(member_openid=member, user_openid="OWNEROPENID000000000000000000"),
    )


async def main():
    failures = []

    bot = make_bot()
    await bot.on_group_at_message_create(group_message("/状态"))
    posts = bot.api.posts
    body = posts[0]["content"] if posts and "content" in posts[0] else (posts[0].get("markdown") or {}).get("content", "")
    ok = bool(posts) and "消息范围" in body and "全量" in body
    print(("ok   " if ok else "FAIL ") + "/状态 回复群状态")
    if not ok:
        failures.append("status")
        print("   posts:", posts[:1])

    bot = make_bot()
    await bot.on_group_at_message_create(group_message("/链接"))
    posts = bot.api.posts
    body = (posts[0].get("content") or (posts[0].get("markdown") or {}).get("content", "")) if posts else ""
    ok = "https://bot.q.qq.com/s/TESTLINK" in body
    print(("ok   " if ok else "FAIL ") + "/链接 返回邀请链接")
    if not ok:
        failures.append("link")

    bot = make_bot()
    await bot.on_group_at_message_create(group_message("/帮助"))
    ok = bool(bot.api.posts)
    print(("ok   " if ok else "FAIL ") + "/帮助 有回复")
    if not ok:
        failures.append("help")

    print("ALL PASS" if not failures else f"{len(failures)} FAILED")
    return 0 if not failures else 1


sys.exit(asyncio.run(main()))
