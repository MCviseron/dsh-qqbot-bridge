"""Quote recognition: platform msg_elements + msg_idx pool fallback (offline)."""
import asyncio
import dataclasses
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path('.').resolve()))
import main as M  # noqa: E402
from main import DSHBot, PooledMessage, load_config  # noqa: E402

REF_A = "REFIDX_Va1QXgH9XPMpoCdgZcchdogmkHICDjIm81"
REF_B = "REFIDX_HBGjHEIroev5tdT2nCIVRqHY6bQLRYDFzfUay0o92R"


class _RT:
    def __init__(self, probe=False):
        self.probe = probe

    def get_bool(self, key, default=True):
        if key == "group_at_only":
            return False
        return self.probe if key == "quote_probe" else default

    def get_int(self, key, default=0):
        return 0 if key == "debounce_ms" else default

    def get_float(self, key, default=0.0):
        return default

    def get_str(self, key, default=""):
        return default

    def get(self, key, default=None):
        return default


class StubAPI:
    async def post_c2c_message(self, **kw):
        return {"id": "m"}

    async def post_c2c_stream_message(self, openid, **fields):
        return {"id": "s"}


class StubBridge:
    def __init__(self):
        self.calls = []

    async def inbound(self, **kw):
        self.calls.append(kw)
        return {"ok": True}

    async def pull(self, cursor, wait):
        return {"cursor": 0, "events": []}


class Msg:
    def __init__(self, scene_ext=None, elements=None, message_id="M1", content="看看这个"):
        scene = {"ext": list(scene_ext), "source": "default"} if scene_ext is not None else None
        raw = {}
        if scene:
            raw["message_scene"] = scene
        if elements is not None:
            raw["msg_elements"] = elements
        self.raw = raw
        self.id = message_id
        self.content = content
        self.attachments = None
        self.author = type("A", (), {"user_openid": "OWNER", "member_openid": "OWNER"})()


def make_bot():
    config = dataclasses.replace(load_config(), ack_delay_s=0, debounce_s=0.0, debounce_max_s=0.0)
    bot = DSHBot.__new__(DSHBot)
    bot.config = config
    bot.api = StubAPI()
    bot.bridge = StubBridge()
    bot.state = type("S", (), {"owner_openid": "OWNER", "group_owners": {}, "save": lambda self: None})()
    bot.owner_openid = "OWNER"
    bot.rt = _RT()
    bot.pool = {}
    bot._chat_turns = {}
    bot.member_index = {}
    bot.pool_idx = {}
    bot._pending_quotes = {}
    bot._suppress_reply = set()
    bot._seen_ids = {}
    bot._streamed_turns = {}
    bot._streams = {}
    bot._urgent_tasks = set()
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
    bot.pending = {}
    bot.targets = {}
    bot.pending_approvals = {}
    bot.group_state = {}
    bot.chime = {}
    bot._msg_seq = 0
    bot._acks = {}
    bot._pull_task = None
    bot._watchdog_task = None
    bot._in_quiet_hours = lambda: False
    return bot


def check(name, ok, extra=""):
    print(("ok   " if ok else "FAIL ") + name + (f" {extra}" if extra else ""))
    return 0 if ok else 1


async def main():
    os.environ["QUOTE_PROBE"] = "0"
    failures = 0

    failures += check("ext 解析成字典",
                      M._scene_ext({"ext": [f"ref_msg_idx={REF_A}", f"msg_idx={REF_B}", "auth_token=x"]})
                      == {"ref_msg_idx": REF_A, "msg_idx": REF_B, "auth_token": "x"})
    failures += check("出站序号取 ext_info.ref_idx",
                      M._sent_idx({"id": "x", "ext_info": {"ref_idx": REF_A}}) == REF_A)

    bot = make_bot()
    element_msg = Msg(elements=[{"content": "被引用的原话", "message_type": 103, "msg_idx": REF_A}])
    quote = bot._quote_of(element_msg)
    failures += check("平台直接给出被引用正文",
                      quote and quote["resolved"] and quote["text"] == "被引用的原话", str(quote))

    bot.pool["MID-1"] = PooledMessage(
        message_id="MID-1", conv_key="group:G", kind="group", openid="G",
        author="主人", text="被引用的原话", outbound=False, at=time.time(), idx=REF_A)
    bot.pool_idx[REF_A] = "MID-1"
    quote = bot._quote_of(element_msg)
    failures += check("正文 + 池里补出作者",
                      quote and quote["author"] == "主人" and quote["text"] == "被引用的原话", str(quote))

    pool_only = Msg(scene_ext=[f"ref_msg_idx={REF_A}", f"msg_idx={REF_B}"])
    quote = bot._quote_of(pool_only)
    failures += check("没有 msg_elements 时用池兜底",
                      quote and quote["resolved"] and quote["text"] == "被引用的原话", str(quote))

    missing = Msg(scene_ext=[f"ref_msg_idx=REFIDX_UNKNOWN00000", f"msg_idx={REF_B}"])
    quote = bot._quote_of(missing)
    failures += check("查不到就如实说看不到", quote and quote["resolved"] is False and quote["text"] == "")

    plain = bot._quote_of(Msg(scene_ext=[f"msg_idx={REF_B}"]))
    failures += check("只有 msg_idx 不算引用", plain is None)

    failures += check("无 raw 不抛异常", bot._quote_of(Msg()) is None)

    bot = make_bot()
    bot._register("c2c:OWNER", "c2c", "OWNER", "M1")
    await bot._handle_c2c(Msg(elements=[{"content": "被引用的原话", "message_type": 103, "msg_idx": REF_A}]))
    await asyncio.sleep(0.3)
    sent = bot.bridge.calls[-1] if bot.bridge.calls else {}
    q = sent.get("quote")
    failures += check("端到端：入站带上被引用正文", bool(q) and q["resolved"] and q["text"] == "被引用的原话", str(q))


    # --- 引用来源区分：机器人本人 / 主人 / 群友 ---
    bot = make_bot()
    bot.pool["OUT-1"] = PooledMessage(
        message_id="OUT-1", conv_key="group:G", kind="group", openid="G",
        author=bot.config.botname, text="我自己说过的话", outbound=True, at=time.time(), idx="REFIDX_OWN000000001")
    bot.pool_idx["REFIDX_OWN000000001"] = "OUT-1"
    q_own = bot._quote_of(Msg(elements=[{"content": "我自己说过的话", "message_type": 103, "msg_idx": "REFIDX_OWN000000001"}]))
    failures += check("引用机器人自己的话标成你自己",
                      q_own and q_own["outbound"] is True and "机器人" in q_own["author"], str(q_own))

    bot.pool["IN-1"] = PooledMessage(
        message_id="IN-1", conv_key="group:G", kind="group", openid="G",
        author="主人", text="主人说的话", outbound=False, at=time.time(), idx="REFIDX_OWNR0000001")
    bot.pool_idx["REFIDX_OWNR0000001"] = "IN-1"
    q_owner = bot._quote_of(Msg(elements=[{"content": "主人说的话", "message_type": 103, "msg_idx": "REFIDX_OWNR0000001"}]))
    failures += check("引用主人标成主人", q_owner and q_owner["author"] == "主人", str(q_owner))

    bot.pool["IN-2"] = PooledMessage(
        message_id="IN-2", conv_key="group:G", kind="group", openid="G",
        author="群友AFF7F1", text="群友说的话", outbound=False, at=time.time(), idx="REFIDX_MATE0000001")
    bot.pool_idx["REFIDX_MATE0000001"] = "IN-2"
    q_mate = bot._quote_of(Msg(elements=[{"content": "群友说的话", "message_type": 103, "msg_idx": "REFIDX_MATE0000001"}]))
    failures += check("引用群友标成群友", q_mate and q_mate["author"] == "群友AFF7F1", str(q_mate))

    # --- 图片 / 文件引用（平台没给正文时按种类标注） ---
    q_img = bot._quote_of(Msg(elements=[{"message_type": 101, "attachments": [{"url": "x"}], "msg_idx": "REFIDX_IMG00000001"}]))
    failures += check("引用图片标成图片", q_img and q_img["kind"] == "image" and q_img["resolved"] is True, str(q_img))

    q_file = bot._quote_of(Msg(elements=[{"message_type": 102, "file_name": "报告.pdf", "msg_idx": "REFIDX_FILE0000001"}]))
    failures += check("引用文件带出文件名", q_file and q_file["kind"] == "file" and q_file["text"] == "报告.pdf", str(q_file))


    # --- 私聊：message_reference 形态的引用 ---
    bot = make_bot()
    bot.pool["C2C-OUT"] = PooledMessage(
        message_id="C2C-OUT", conv_key="c2c:OWNER", kind="c2c", openid="OWNER",
        author=bot.config.botname, text="我私聊里说过的话", outbound=True, at=time.time(), idx="")
    ref_msg = Msg()
    ref_msg.raw = {"message_reference": {"message_id": "C2C-OUT"}}
    q_ref = bot._quote_of(ref_msg)
    failures += check("私聊 message_reference 命中池并标成机器人",
                      q_ref and q_ref["resolved"] and q_ref["outbound"] is True and q_ref["text"] == "我私聊里说过的话",
                      str(q_ref))

    ref_text = Msg()
    ref_text.raw = {"message_reference": {"message_id": "C2C-GONE", "content": "平台直接给的正文"}}
    q_text = bot._quote_of(ref_text)
    failures += check("私聊引用带正文时直接用",
                      q_text and q_text["resolved"] and q_text["text"] == "平台直接给的正文", str(q_text))

    none_ref = Msg()
    none_ref.raw = {"content": "没有引用的普通私聊"}
    failures += check("私聊无 message_reference 不算引用", bot._quote_of(none_ref) is None)


    # --- 引用图片：取出 URL 并交给下载流程 ---
    failures += check("attachment url 解析", M._attachment_url({"url": "https://x/a.png"}) == "https://x/a.png"
                      and M._attachment_url({"file_url": "https://x/b.png"}) == "https://x/b.png"
                      and M._attachment_url("https://x/c.png") == "https://x/c.png"
                      and M._attachment_url({}) is None)

    img_quote = bot._quote_of(Msg(elements=[{"message_type": 101, "attachments": [{"url": "https://cdn/x.jpg"}], "msg_idx": "REFIDX_IMGSAMPLE01"}]))
    failures += check("引用图片带出 urls", img_quote and img_quote["kind"] == "image" and img_quote["urls"] == ["https://cdn/x.jpg"], str(img_quote))
    failures += check("没有 url 时不下载", (await bot._quote_images({"kind": "image", "urls": []})) == [])

    print("ALL PASS" if failures == 0 else f"{failures} FAILED")
    return 0 if failures == 0 else 1


sys.exit(asyncio.run(main()))
