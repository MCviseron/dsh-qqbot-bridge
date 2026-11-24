"""DSH QQ bot: the QQ face of DeepSeek Harness.

Every QQ message is forwarded to the local dsh-qq-bridge DSH plugin, which owns
one DSH Session per conversation; the agent's answer comes back through the same
channel. Tool approvals are relayed to the bot owner's private chat, and only
that owner may answer them.

The viseron_qqbotpy SDK is used read-only: nothing in this file modifies it.
"""
from __future__ import annotations

import aiohttp
import argparse
import asyncio
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from viseron_qqbotpy import C2CMessage, Client, GroupMessage, Intents, Interaction
from viseron_qqbotpy import configure_logging, load_env, get_logger, load_panels

from bridge import BridgeClient, BridgeError, download_image

ROOT = Path(__file__).resolve().parent
SG_GROUP_BASE_URL = "https://api.sgroup.qq.com"
STATE_FILE = ROOT / "state.json"
CURSOR_FILE = ROOT / "state" / "cursor.txt"

# One QQ passive reply slot expires after 5 minutes, and one user message may be
# answered at most 5 times; both limits are enforced locally before the API call.
PASSIVE_WINDOW_S = 240.0
MAX_PASSIVE_PER_MESSAGE = 5

# 消息池：缓存最近 10 分钟的收发消息，供 /撤回 挑一条撤销
MSG_POOL_TTL_S = 1800.0
MSG_POOL_MAX = 100

ALLOW_WORDS = {"允许", "同意", "可以", "批准", "y", "yes", "ok", "allow", "approve"}
DENY_WORDS = {"拒绝", "不行", "不允许", "驳回", "n", "no", "deny", "reject"}
RESET_COMMANDS = {"/reset", "reset", "/新会话", "新会话", "/重置", "重置", "清空上下文", "/清空"}
HELP_COMMANDS = {"/help", "help", "/帮助", "帮助", "/dsh"}
BIND_COMMANDS = {"/绑定", "/绑定主人", "绑定主人"}
STATE_COMMANDS = {"/状态", "/status", "状态"}
LINK_COMMANDS = {"/链接", "/邀请", "/invite", "邀请链接"}
SHOT_COMMANDS = {"/截图", "/screenshot", "/shot", "截图"}
WINDOW_COMMANDS = {"/窗口", "/windows", "窗口"}
SESSION_COMMANDS = {"/会话", "/sessions", "会话", "/当前会话"}
SWITCH_COMMANDS = {"/切会话", "/切换", "/switch", "切会话"}
BACK_COMMANDS = {"/切回", "/返回", "/back", "切回"}
USAGE_COMMANDS = {"/花费", "/用量", "/token", "/usage", "/cost", "花费", "用量"}
MENU_COMMANDS = {"/菜单", "/指令", "/面板", "/menu", "/commands", "菜单", "指令"}
RECALL_COMMANDS = {"/撤回", "/recall", "撤回"}
POOL_COMMANDS = {"/消息池", "/池", "/pool", "消息池"}
URGENT_EVENTS = {"approval", "notice"}
# Commands that touch the host machine, cost accounting, or a Session binding:
# non-owners may not run them (checked inside handle_extra_command).
OWNER_ONLY_COMMANDS = (
    SHOT_COMMANDS | WINDOW_COMMANDS | USAGE_COMMANDS | SESSION_COMMANDS
    | SWITCH_COMMANDS | BACK_COMMANDS | STATE_COMMANDS | LINK_COMMANDS | POOL_COMMANDS
)

CAPTURE_SCRIPT = ROOT.parent / "tools" / "window-capture.ps1"
SHOT_DIR = ROOT.parent / "shots"
STICKER_DIR = ROOT.parent / "assets" / "stickers"
# 模型想发表情包时写 [[sticker: 名字]]，机器人从 assets/stickers 里取图发出去
STICKER_MARK = re.compile(r"\[\[sticker\s*[:：]\s*([^\]]+?)\]\]", re.IGNORECASE)
NO_REPLY_MARK = "[NO_REPLY]"

# 模型用这个标记把本地文件交回 QQ：[[send_file: D:\path\pic.png]]
SEND_FILE_MARK = re.compile(r"\[\[(?:send_file|send_image|发送文件|发图)\s*[:：]\s*([^\]]+?)\]\]", re.IGNORECASE)
# 扩展名 → QQ 富媒体 file_type（1 图片 2 视频 3 语音 4 文件）
FILE_TYPES = {
    ".png": 1, ".jpg": 1, ".jpeg": 1, ".gif": 1, ".webp": 1, ".bmp": 1,
    ".mp4": 2, ".mov": 2,
    ".silk": 3, ".amr": 3, ".mp3": 3, ".wav": 3,
}

CODE_FENCE = "\x60\x60\x60"
MD_LINE = re.compile(r"(^|\n)\s*(#{1,6} |[-*+] |\d+\. |\|\s*\S)")
MD_INLINE = re.compile(r"\*\*[^*\n]+\*\*")

log = get_logger()


# --------------------------------------------------------------------------- #
# configuration
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Config:
    """Everything the transport needs; secrets come from .env only."""

    appid: str
    secret: str
    botname: str
    bridge_url: str
    bridge_token: str
    owner_openid: str
    sandbox: bool
    http_timeout: float
    groups_enabled: bool
    group_full_mode: bool
    owner_role_check: bool
    max_chars: int
    pull_wait_ms: int
    ack_delay_s: float
    ack_text: str
    debounce_s: float
    debounce_max_s: float
    chime_min: int
    chime_cooldown_s: float
    md_auto: bool
    image_max_mb: float
    send_file_roots: Tuple[str, ...]
    bot_aliases: Tuple[str, ...]
    stale_prompt_s: float
    owner_window_s: float
    group_chat_window_s: float
    chatter_batch: int
    chatter_max_s: float
    chatter_cooldown_s: float
    bot_say_memory_s: float
    stuck_turn_s: float


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return default if value is None or value.strip() == "" else value.strip()


def _env_flag(name: str, default: bool) -> bool:
    raw = _env(name, "1" if default else "0").lower()
    return raw in {"1", "true", "yes", "on"}


def load_config() -> Config:
    """Read .env + environment; fail fast with an actionable message."""
    load_env(ROOT / ".env")
    appid = _env("APPID")
    secret = _env("APPSECRET") or _env("APPSECERT")
    if not appid or not secret:
        raise SystemExit("APPID / APPSECRET missing: copy .env.example to .env and fill them in.")
    return Config(
        appid=appid,
        secret=secret,
        botname=_env("BOTNAME", "DSH"),
        bridge_url=_env("BRIDGE_URL", "http://127.0.0.1:39061"),
        bridge_token=_env("BRIDGE_TOKEN"),
        owner_openid=_env("OWNER_OPENID"),
        sandbox=_env_flag("QQ_SANDBOX", False),
        http_timeout=float(_env("HTTP_TIMEOUT", "60")),
        groups_enabled=_env_flag("GROUP_ENABLED", True),
        group_full_mode=_env_flag("GROUP_FULL_MODE", False),
        owner_role_check=_env_flag("OWNER_ROLE_CHECK", True),
        max_chars=int(_env("MAX_CHARS", "1600")),
        pull_wait_ms=int(_env("PULL_WAIT_MS", "25000")),
        ack_delay_s=float(_env("ACK_DELAY_S", "12")),
        ack_text=_env("ACK_TEXT", "（还在处理，请稍等…）"),
        debounce_s=float(_env("DEBOUNCE_MS", "1800")) / 1000.0,
        debounce_max_s=float(_env("DEBOUNCE_MAX_MS", "6000")) / 1000.0,
        chime_min=int(_env("GROUP_CHIME_MIN", "8")),
        chime_cooldown_s=float(_env("GROUP_CHIME_COOLDOWN", "240")),
        md_auto=_env_flag("MD_AUTO", True),
        image_max_mb=float(_env("IMAGE_MAX_MB", "8")),
        send_file_roots=tuple(
            part.strip() for part in _env("SEND_FILE_ROOTS", str(ROOT.parent)).split(";") if part.strip()
        ),
        bot_aliases=tuple(
            part.strip()
            for part in _env("BOT_ALIASES", "蓝色大肥鱼,大肥鱼,机器人,DSH,dsh").split(",")
            if part.strip()
        ),
        stale_prompt_s=float(_env("STALE_PROMPT_S", "90")),
        owner_window_s=float(_env("OWNER_WINDOW_S", "180")),
        group_chat_window_s=float(_env("GROUP_CHAT_WINDOW_S", "300")),
        chatter_batch=int(_env("GROUP_CHATTER_BATCH", "8")),
        chatter_max_s=float(_env("GROUP_CHATTER_MAX_S", "120")),
        chatter_cooldown_s=float(_env("GROUP_CHATTER_COOLDOWN_S", "45")),
        bot_say_memory_s=float(_env("BOT_SAY_MEMORY_S", "300")),
        stuck_turn_s=float(_env("STUCK_TURN_S", "180")),
    )


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
# QQ 把表情/图片/按钮等编码成这种内联标签，喂给模型前先清掉
INLINE_TAG = re.compile(r"<(?:faceType|img|qqbot-cmd-enter|qqbot-at-user|emoji)[^>]*>", re.IGNORECASE)


def _author_nick(message: Any) -> str:
    """The sender's nickname as the platform reports it (username, else group card)."""
    author = getattr(message, "author", None)
    for value in (
        getattr(author, "username", "") if author is not None else "",
        getattr(author, "member_nickname", "") if author is not None else "",
        getattr(message, "member_nickname", "") or "",
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def clean_content(content: Optional[str]) -> str:
    """Strip @bot markup, inline QQ tags, and surrounding whitespace."""
    text = (content or "").strip()
    while text.startswith("<@") and ">" in text:
        text = text.split(">", 1)[1].lstrip()
    text = INLINE_TAG.sub("", text)
    return " ".join(text.split()).strip()


def looks_like_openid(value: str) -> bool:
    """Guard against answering synthetic ids such as the CLI smoke tests."""
    return len(value) >= 16 and "-" not in value and value.isalnum()


def short_id(value: str) -> str:
    """Stable short tag for an openid, so a name stays readable in chat."""
    return value[-6:] if len(value) > 6 else value


def looks_like_markdown(text: str) -> bool:
    """Whether a reply should go out as a QQ Markdown message (msg_type=2)."""
    if CODE_FENCE in text:
        return True
    if MD_LINE.search(text) is not None:
        return True
    return MD_INLINE.search(text) is not None


def chunk_text(text: str, limit: int) -> List[str]:
    """Split long answers on paragraph/line boundaries, then hard-cut."""
    if limit <= 0 or len(text) <= limit:
        return [text]
    chunks: List[str] = []
    buffer = ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            if buffer:
                chunks.append(buffer)
                buffer = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(buffer) + len(line) > limit:
            chunks.append(buffer)
            buffer = line
        else:
            buffer += line
    if buffer:
        chunks.append(buffer)
    return [chunk for chunk in (part.strip("\n") for part in chunks) if chunk != ""]


def parse_kick_confirm(text: str) -> Optional[Tuple[str, bool]]:
    """'踢人确认 <id> yes|no' as sent by the confirmation buttons."""
    match = re.search(r"踢人确认\s+(\S+)\s+(yes|no)", text or "", re.IGNORECASE)
    if not match:
        return None
    return match.group(1), match.group(2).lower() == "yes"


def parse_decision(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Recognise an approval answer, optionally carrying the approval id."""
    tokens = text.strip().split()
    if not tokens:
        return None, None
    head = tokens[0].strip("：:，,。.!！~～").lower()
    approval_id = tokens[1] if len(tokens) > 1 else None
    if head in ALLOW_WORDS:
        return "allow", approval_id
    if head in DENY_WORDS:
        return "reject", approval_id
    return None, None


COMMAND_PANEL_ROWS = [
    [("/帮助", "帮助"), ("/状态", "状态"), ("/会话", "会话")],
    [("/花费", "花费"), ("/花费 全部", "花费全部"), ("/新会话", "新会话")],
    [("/截图", "截图"), ("/窗口", "窗口"), ("/菜单", "菜单")],
]


def command_keyboard() -> Dict[str, Any]:
    """Command panel: every button sends its command as a normal message."""
    rows = []
    for row in COMMAND_PANEL_ROWS:
        buttons = []
        for data, label in row:
            buttons.append(
                {
                    "id": data,
                    "render_data": {"label": label, "visited_label": label, "style": 1},
                    "action": {
                        "type": 2,
                        "permission": {"type": 2},
                        "data": data,
                        "unsupport_tips": f"请升级 QQ 后使用按钮，或直接回复「{data}」",
                        "enter": True,
                    },
                }
            )
        rows.append({"buttons": buttons})
    return {"content": {"rows": rows}}


def question_keyboard(question_id: str, options: list) -> Dict[str, Any]:
    """One button per option; clicking answers the pending dsh question."""
    buttons = []
    for index, label in enumerate(options[:8]):
        text = str(label)
        buttons.append({
            "id": f"{question_id}:{index}",
            "render_data": {"label": text[:12], "visited_label": "✓ 已选", "style": 1},
            "action": {
                "type": 1,
                "permission": {"type": 2},
                "click_limit": 1,
                "data": f"选择 {question_id} {index}",
                "unsupport_tips": "请升级 QQ 后使用按钮，或直接回复选项序号",
            },
        })
    rows = [{"buttons": buttons[i:i + 2]} for i in range(0, len(buttons), 2)]
    return {"content": {"rows": rows}}


def kick_confirm_keyboard(request_id: str) -> Dict[str, Any]:
    """Owner-only second confirmation for an irreversible kick."""
    def button(label: str, style: int, data: str, visited: str) -> Dict[str, Any]:
        return {
            "id": data,
            "render_data": {"label": label, "visited_label": visited, "style": style},
            "action": {
                "type": 1,
                "permission": {"type": 2},
                "data": data,
                "unsupport_tips": "请升级 QQ 后使用按钮，或直接回复「确认踢人」/「取消踢人」",
            },
        }

    return {
        "content": {
            "rows": [
                {
                    "buttons": [
                        button("确认踢出", 3, f"踢人确认 {request_id} yes", "✓ 已踢出"),
                        button("取消", 0, f"踢人确认 {request_id} no", "✓ 已取消"),
                    ]
                }
            ]
        }
    }


def decided_keyboard(approval_id: str, label: str) -> Dict[str, Any]:
    """Keyboard for an already-decided approval: one dead button that only toasts."""
    return {
        "content": {
            "rows": [
                {
                    "buttons": [
                        {
                            "id": "1",
                            "render_data": {"label": "已处理 ✅", "visited_label": "已处理 ✅", "style": 0},
                            "action": {
                                "type": 1,
                                "permission": {"type": 0},
                                "data": f"已处理 {approval_id}"[:40],
                                "unsupport_tips": "已处理",
                            },
                        }
                    ]
                }
            ]
        }
    }


def approval_keyboard(approval_id: str) -> Dict[str, Any]:
    """Two-button keyboard: 允许 / 拒绝, clicked value carries the approval id."""

    def button(label: str, style: int, data: str, visited: str) -> Dict[str, Any]:
        return {
            "id": data,
            # visited_label：点完之后客户端把按钮就地改成这个文案（官方同款做法）
            "render_data": {"label": label, "visited_label": visited, "style": style},
            "action": {
                # 官方 dsh-qqbot 的审批键盘用的就是 action.type=1 + permission.type=2
                # （permission.type: 0 会被平台直接判成"无权限操作"）
                "type": 1,
                "permission": {"type": 2},
                "data": data,
                "unsupport_tips": "请升级 QQ 后使用按钮，或直接回复「允许」/「拒绝」",
            },
        }

    return {
        "content": {
            "rows": [
                {
                    "buttons": [
                        button("允许", 1, f"允许 {approval_id}", "✓ 已允许"),
                        button("拒绝", 0, f"拒绝 {approval_id}", "✓ 已拒绝"),
                    ]
                }
            ]
        }
    }


# --------------------------------------------------------------------------- #
# local state (owner identity + bound group owners)
# --------------------------------------------------------------------------- #
class LocalState:
    """Owner identity per bot appid, plus per-group owner bindings."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.owner_openid = ""
        self.group_owners: Dict[str, str] = {}

    def load(self) -> "LocalState":
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return self
        if isinstance(data, dict):
            owner = data.get("owner_openid")
            if isinstance(owner, str):
                self.owner_openid = owner
            bound = data.get("group_owners")
            if isinstance(bound, dict):
                self.group_owners = {str(k): str(v) for k, v in bound.items()}
        return self

    def save(self) -> None:
        payload = {"owner_openid": self.owner_openid, "group_owners": self.group_owners}
        try:
            self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as error:  # pragma: no cover - best effort
            log.warning("could not persist %s: %s", self.path, error)


# --------------------------------------------------------------------------- #
# reply target bookkeeping
# --------------------------------------------------------------------------- #
@dataclass
class Target:
    """Where latest messages of one conversation go, and the passive window."""

    conv_key: str
    kind: str
    openid: str
    last_msg_id: Optional[str] = None
    last_msg_at: float = 0.0
    passive_used: int = 0

    def remember(self, message_id: Optional[str]) -> None:
        if message_id:
            self.last_msg_id = message_id
            self.last_msg_at = time.time()
            self.passive_used = 0

    def passive_slot(self) -> Optional[str]:
        """A msg_id we may still answer passively, if one is available."""
        if not self.last_msg_id:
            return None
        if time.time() - self.last_msg_at > PASSIVE_WINDOW_S:
            return None
        if self.passive_used >= MAX_PASSIVE_PER_MESSAGE:
            return None
        self.passive_used += 1
        return self.last_msg_id


@dataclass
class PooledMessage:
    """One recent message (in or out) kept so /撤回 can reach it by index."""

    message_id: str
    conv_key: str
    kind: str
    openid: str
    author: str
    text: str
    outbound: bool
    at: float
    idx: str = ""


@dataclass
class Chatter:
    """Chatter buffered between judgments for one group."""

    lines: List[str] = field(default_factory=list)
    first_at: float = 0.0
    last_judge_at: float = 0.0
    timer: Optional[asyncio.Task] = None


@dataclass
class QueuedPrompt:
    """Messages that piled up while a turn was still running for this chat."""

    parts: List[str] = field(default_factory=list)
    images: List[Dict[str, str]] = field(default_factory=list)
    sender_name: str = ""
    is_owner: bool = False
    chime: bool = False
    chat: bool = False
    first_at: float = field(default_factory=time.time)


@dataclass
class Pending:
    """Messages being debounced into one prompt for a conversation."""

    parts: List[str] = field(default_factory=list)
    images: List[Dict[str, str]] = field(default_factory=list)
    sender_name: str = ""
    is_owner: bool = False
    chat: bool = False
    started: float = field(default_factory=time.time)
    job: Optional[asyncio.Task] = None


# --------------------------------------------------------------------------- #
# the bot
# --------------------------------------------------------------------------- #
class DSHBot(Client):
    """QQ transport in front of the dsh-qq-bridge plugin."""

    def __init__(self, intents: Intents, *, config: Config) -> None:
        super().__init__(intents, timeout=config.http_timeout, is_sandbox=config.sandbox)
        self.config = config
        self.bridge = BridgeClient(config.bridge_url, config.bridge_token)
        self.state = LocalState(STATE_FILE).load()
        self.owner_openid = config.owner_openid or self.state.owner_openid
        if config.owner_openid and config.owner_openid != self.state.owner_openid:
            self.state.owner_openid = config.owner_openid
            self.state.save()
        self.targets: Dict[str, Target] = {}
        self.pending_approvals: Dict[str, Dict[str, Any]] = {}
        self._decided: Dict[str, str] = {}
        self._streams: Dict[str, Dict[str, Any]] = {}
        self._suppress_reply: set = set()
        self._streamed_turns: Dict[str, float] = {}

        self.pending: Dict[str, Pending] = {}
        self.queued: Dict[str, QueuedPrompt] = {}
        self.chatter: Dict[str, Chatter] = {}
        self.recent_images: Dict[str, Tuple[List[Dict[str, str]], float]] = {}
        self._addressed_at: Dict[str, float] = {}
        self._bot_spoke_at: Dict[str, float] = {}
        self._last_sent: Dict[str, Tuple[str, float]] = {}
        self._last_bot_say: Dict[str, Tuple[str, float]] = {}
        self._rate: Dict[str, Tuple[int, float]] = {}
        self.rt = None  # type: ignore[assignment]
        self.group_state: Dict[str, Dict[str, Any]] = {}
        self._role_probe_failed_at = 0.0
        self._seen_ids: Dict[str, float] = {}
        self._submitted_at: Dict[str, float] = {}
        self._urgent_tasks: set = set()
        self._inflight: Dict[str, int] = {}
        self._inflight_at: Dict[str, float] = {}
        self.chime: Dict[str, Dict[str, float]] = {}
        self._msg_seq = 0
        self._pull_task: Optional[asyncio.Task] = None
        self._watchdog_task: Optional[asyncio.Task] = None
        self._acks: Dict[str, asyncio.Task] = {}
        self.pool: Dict[str, PooledMessage] = {}
        self.pool_idx: Dict[str, str] = {}
        self._pending_quotes: Dict[str, Dict[str, Any]] = {}
        self._started_at = time.time()
        self._chat_turns: Dict[str, bool] = {}
        self._bg_tasks: set = set()
        self._owner_recent: Dict[str, float] = {}
        self._last_group_at: Dict[str, float] = {}
        self._stream_locks: Dict[str, asyncio.Lock] = {}
        self._stream_holdoff: Dict[str, float] = {}
        self._admin_confirm: Dict[str, Dict[str, Any]] = {}
        self.member_index: Dict[str, Dict[str, str]] = {}
        self._token: Tuple[str, float] = ("", 0.0)

    # -- lifecycle ---------------------------------------------------------- #
    async def on_ready(self) -> None:
        log.info("[%s] bot online (owner=%s)", self.config.botname, self.owner_openid or "unclaimed")
        try:
            health = await self.bridge.health()
            log.info("[%s] bridge %s (%s)", self.config.botname, health.get("service"), self.config.bridge_url)
        except BridgeError as error:
            log.warning("[%s] bridge unreachable: %s", self.config.botname, error)
        self._seed_metrics()  # 计数跨重启累计，只有「运行时长」归零
        self._bump("c2c_msgs", 0)  # 初始化并落盘计数器，仪表盘开局就有数据
        self._prune_metrics(time.time())  # 启动时清一次超过保留期的归档
        await self._prefetch_group_profiles()
        await self._sync_panels()
        # 严格闭合：重启后先把上个进程遗留的流式会话关掉，再开始新回合
        try:
            await self._close_stale_streams()
        except Exception as error:  # noqa: BLE001 - must never block startup
            log.warning("stale stream cleanup failed: %s", error)
        _heartbeat()
        if self._pull_task is None or self._pull_task.done():
            self._pull_task = asyncio.create_task(self._pull_loop())
        if getattr(self, "_watchdog_task", None) is None or self._watchdog_task.done():
            self._watchdog_task = asyncio.create_task(self._pull_watchdog())
        self._question_task = asyncio.create_task(self._question_loop())
        self._admin_task = asyncio.create_task(self._admin_loop())

    async def _sync_panels(self) -> None:
        """Push bot/panels/panels.json to the QQ instruction panel."""
        try:
            store = await load_panels(self.api, root_dir=str(ROOT / "panels"))
            await store.sync_from_config()
            log.info("[%s] instruction panels synced", self.config.botname)
        except Exception as error:  # noqa: BLE001 - panel sync must never block startup
            log.warning("[%s] panel sync failed: %s", self.config.botname, error)

    # -- runtime settings (panel-editable, hot-reloaded) -------------------- #
    def rt_bool(self, key: str, default: bool = True) -> bool:
        return self.rt.get_bool(key) if self.rt is not None else default

    def rt_int(self, key: str, default: int = 0) -> int:
        return self.rt.get_int(key) if self.rt is not None else default

    def rt_float(self, key: str, default: float = 0.0) -> float:
        return self.rt.get_float(key) if self.rt is not None else default

    def rt_str(self, key: str, default: str = "") -> str:
        if self.rt is None:
            return default
        value = self.rt.get(key)
        return default if value is None else str(value)

    def _allowlisted(self, key: str, ident: str) -> bool:
        raw = self.rt_str(key, "")
        if raw.strip() == "":
            return True
        return any(part.strip() == ident for part in raw.split(",") if part.strip())

    def _in_quiet_hours(self) -> bool:
        if not self.rt_bool("quiet_enabled", True):
            return False
        raw = self.rt_str("quiet_hours", "").strip()
        if not raw or "-" not in raw:
            return False
        try:
            start_text, end_text = raw.split("-", 1)
            now = time.strftime("%H:%M")
            start, end = start_text.strip(), end_text.strip()
            return (start <= now < end) if start <= end else (now >= start or now < end)
        except Exception:
            return False

    def _rate_limited(self, conv_key: str) -> bool:
        limit = self.rt_int("rate_limit_per_hour", 0)
        if limit <= 0:
            return False
        count, window = self._rate.get(conv_key, (0, time.time()))
        if time.time() - window > 3600:
            count, window = 0, time.time()
        self._rate[conv_key] = (count, window)
        if count >= limit:
            log.warning("rate limited %s (%d/h)", conv_key, limit)
            return True
        return False

    def _count_send(self, conv_key: str) -> None:
        count, window = self._rate.get(conv_key, (0, time.time()))
        if time.time() - window > 3600:
            count, window = 0, time.time()
        self._rate[conv_key] = (count + 1, window)

    # -- helpers ------------------------------------------------------------ #
    @staticmethod
    def _target_from_key(conv_key: str) -> Optional[Target]:
        kind, _, openid = conv_key.partition(":")
        if not openid or kind not in {"group", "c2c"}:
            return None
        return Target(conv_key=conv_key, kind=kind, openid=openid)

    def _register(self, conv_key: str, kind: str, openid: str, message_id: Optional[str]) -> Target:
        target = self.targets.get(conv_key)
        if target is None:
            target = Target(conv_key=conv_key, kind=kind, openid=openid)
            self.targets[conv_key] = target
        target.openid = openid or target.openid
        target.remember(message_id)
        return target

    @staticmethod
    def conv_label(conv_key: str) -> str:
        """Human-facing name for a conversation key (approval cards, logs)."""
        kind, _, openid = conv_key.partition(":")
        if kind == "group":
            return f"QQ 群 …{short_id(openid)}"
        if kind == "c2c":
            return f"QQ 私聊 …{short_id(openid)}"
        return conv_key

    def _owner_conv(self) -> str:
        return f"c2c:{self.owner_openid}" if self.owner_openid else ""

    def _is_owner_group(self, group_openid: str, member_openid: str) -> bool:
        if member_openid == "":
            return False
        # The bot owner is the owner everywhere, even in a group nobody bound.
        if self.owner_openid and member_openid == self.owner_openid:
            return True
        return self.state.group_owners.get(group_openid, "") == member_openid

    async def _bind_group_owner_by_role(self, group_openid: str, member_openid: str) -> bool:
        """Ask the platform whether this member owns the group, then remember it."""
        if not self.config.owner_role_check or not member_openid:
            return False
        if self._is_owner_group(group_openid, member_openid):
            return True
        try:
            if time.time() - self._role_probe_failed_at < 900:
                return False
            info = await self.api.get_group_member(group_openid=group_openid, member_openid=member_openid)
        except Exception as error:  # noqa: BLE001 - 11253 = capability not opened yet
            self._role_probe_failed_at = time.time()
            log.info("group member lookup unavailable (will retry in 15 min): %s", error)
            return False
        payload = info.get("member") if isinstance(info, dict) and isinstance(info.get("member"), dict) else info
        role = str(payload.get("member_role") or "") if isinstance(payload, dict) else ""
        if role != "owner":
            return False
        self.state.group_owners[group_openid] = member_openid
        self.state.save()
        log.info("group owner detected: %s -> %s", group_openid, short_id(member_openid))
        return True

    def _remember_id(self, message_id: Optional[str]) -> None:
        """Track recently handled message ids so one message is answered once."""
        if not message_id:
            return
        self._seen_ids[message_id] = time.time()
        if len(self._seen_ids) > 500:
            for key in sorted(self._seen_ids, key=self._seen_ids.get)[:250]:
                self._seen_ids.pop(key, None)

    # -- recent message pool (for /撤回) ------------------------------------ #
    def _pool_ttl(self) -> float:
        return max(60.0, self.rt_float("pool_ttl_s", MSG_POOL_TTL_S))

    def _pool_limit(self) -> int:
        return max(10, self.rt_int("pool_max", MSG_POOL_MAX))

    def _pool_add(self, item: PooledMessage) -> None:
        """Keep the last 10 minutes of traffic, oldest evicted first."""
        self.pool[item.message_id] = item
        if item.idx:
            self.pool_idx[item.idx] = item.message_id
        cutoff = time.time() - self._pool_ttl()
        for key in [key for key, value in self.pool.items() if value.at < cutoff]:
            self.pool.pop(key, None)
        while len(self.pool) > self._pool_limit():
            self.pool.pop(next(iter(self.pool)), None)
        if self.pool_idx:
            live = {item.message_id for item in self.pool.values()}
            for idx, message_id in list(self.pool_idx.items()):
                if message_id not in live:
                    self.pool_idx.pop(idx, None)

    def _pool_incoming(self, message: Any, kind: str, openid: str, conv_key: str, author: str) -> None:
        message_id = str(getattr(message, "id", "") or "")
        if not message_id:
            return
        raw = clean_content(getattr(message, "content", ""))
        # 防御：任何时候都不要把我们自己的提示词当成群聊发言记进上下文
        if raw.lstrip().startswith(("【闲聊模式】", "【群聊插话判断】")):
            log.warning("dropped prompt-shaped text from the pool (%s)", kind)
            return
        self._pool_add(
            PooledMessage(
                message_id=message_id,
                conv_key=conv_key,
                kind=kind,
                openid=openid,
                author=author or "群友",
                text=clean_content(getattr(message, "content", ""))[:60],
                outbound=False,
                at=time.time(),
                idx=self._message_idx(message),
            )
        )

    def _pool_sent(self, target: Target, result: Any, text: str) -> None:
        if isinstance(result, dict):
            message_id = str(result.get("id") or "")
        else:
            message_id = str(getattr(result, "id", "") or "")
        if not message_id:
            return
        self._pool_add(
            PooledMessage(
                message_id=message_id,
                conv_key=target.conv_key,
                kind=target.kind,
                openid=target.openid,
                author=self.config.botname,
                text=text[:60],
                outbound=True,
                idx=_sent_idx(result),
                at=time.time(),
            )
        )

    def _pool_items(self, conv_key: str) -> List[PooledMessage]:
        cutoff = time.time() - self._pool_ttl()
        items = [item for item in self.pool.values() if item.conv_key == conv_key and item.at >= cutoff]
        return sorted(items, key=lambda item: item.at)

    def _pool_text(self, conv_key: str) -> str:
        items = self._pool_items(conv_key)
        if not items:
            return "消息池是空的（只缓存最近 10 分钟）。"
        rows = [
            f"{index}. [{int(time.time() - item.at)}s] {'我' if item.outbound else item.author}："
            f"{item.text.replace(chr(10), ' ')[:28] or '(图片/空)'}"
            for index, item in enumerate(items, 1)
        ]
        head = f"最近 10 分钟 {len(items)} 条（/撤回 <序号> 撤指定，/撤回 n 撤我最近 n 条）："
        return "\n".join([head, *rows[-20:]])

    async def _access_token(self) -> str:
        """App access token for raw platform calls (the SDK caches its own copy)."""
        stored = self._token
        # The SDK hands over a TokenManager until our own cache is primed.
        token, expires_at = stored if isinstance(stored, tuple) else ("", 0.0)
        if token and time.time() < expires_at - 60:
            return token
        appid = self.rt_str("appid", self.config.appid)
        secret = self.rt_str("appsecret", self.config.secret)
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                "https://bots.qq.com/app/getAppAccessToken",
                json={"appId": appid, "clientSecret": secret},
            ) as response:
                data = await response.json(content_type=None)
        token = str((data or {}).get("access_token") or "")
        if not token:
            raise RuntimeError(f"取 token 失败：{data}")
        self._token = (token, time.time() + float((data or {}).get("expires_in") or 7200))
        return token

    async def recall_message(self, item: PooledMessage) -> Tuple[bool, str]:
        """DELETE one message: a bot admin may recall its own and members' messages."""
        try:
            token = await self._access_token()
        except Exception as error:  # noqa: BLE001 - surfaced to the caller as text
            return False, f"鉴权失败：{error}"
        appid = self.rt_str("appid", self.config.appid)
        if item.kind == "group":
            url = f"{SG_GROUP_BASE_URL}/v2/groups/{item.openid}/messages/{item.message_id}"
        else:
            url = f"{SG_GROUP_BASE_URL}/v2/users/{item.openid}/messages/{item.message_id}"
        headers = {"Authorization": f"QQBot {token}", "X-Union-Appid": appid}
        timeout = aiohttp.ClientTimeout(total=20)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.delete(url, headers=headers) as response:
                    body = await response.text()
                    ok = response.status == 200
                    log.info(
                        "recall %s/%s status=%s body=%s",
                        item.kind,
                        item.message_id[-8:],
                        response.status,
                        body[:160].replace("\n", " "),
                    )
        except aiohttp.ClientError as error:
            return False, f"请求失败：{error}"
        if ok:
            self.pool.pop(item.message_id, None)
            return True, ""
        hints = {
            "40062003": "没权限（我还是群管理员吗？）",
            "40064004": "已超撤回时限",
            "40061001": "消息 id 无效",
            "50065001": "平台撤回失败，稍后重试",
        }
        try:
            code = str(json.loads(body).get("code") or "")
        except (json.JSONDecodeError, AttributeError):
            code = ""
        return False, hints.get(code, body[:120] or "未知错误")

    async def _recall_command(self, conv_key: str, text: str) -> None:
        parts = text.split(maxsplit=1)
        arg = parts[1].strip() if len(parts) > 1 else ""
        items = self._pool_items(conv_key)
        if not items:
            await self.send_text(conv_key, "消息池是空的（只缓存最近 10 分钟）。")
            return
        outbound = [item for item in items if item.outbound]
        if not arg:
            targets = outbound[-1:]
        elif arg.startswith("#") and arg[1:].isdigit():
            index = int(arg[1:])
            targets = [items[index - 1]] if 1 <= index <= len(items) else []
        elif arg.isdigit():
            targets = outbound[-max(1, min(int(arg), 10)):]
        else:
            targets = [item for item in items if item.message_id.startswith(arg)]
        if not targets:
            await self.send_text(conv_key, f"没找到要撤的消息（{arg or '我最近没发过'}）。")
            return
        done = 0
        failures: List[str] = []
        for item in targets:
            ok, detail = await self.recall_message(item)
            if ok:
                done += 1
            else:
                failures.append(detail)
        message = f"已撤回 {done} 条。" if done else "一条都没撤成。"
        if failures:
            message += "\n失败：" + "；".join(sorted(set(failures))[:3])
        await self.send_text(conv_key, message)

    def _alias_list(self):
        raw = self.rt_str("bot_aliases", ",".join(self.config.bot_aliases))
        return ", ".join(part.strip() for part in raw.split(",") if part.strip())

    def addresses_bot(self, text: str) -> bool:
        """Whether the text names the bot without an explicit @ mention."""
        lowered = text.lower()
        raw = self.rt_str("bot_aliases", ",".join(self.config.bot_aliases))
        aliases = [part.strip() for part in raw.split(",") if part.strip()]
        return any(alias.lower() in lowered for alias in aliases)

    async def _mentions_bot(self, message: GroupMessage) -> bool:
        """Whether this message actually @s the bot (never "any mention")."""
        mentions = getattr(message, "mentions", None) or []
        if not mentions:
            return False

        # Collect every string the platform gave us for each mention.
        candidates: List[str] = []
        flag_bot = False
        for mention in mentions:
            raw = getattr(mention, "raw", None) or {}
            for value in raw.values():
                if isinstance(value, str) and value:
                    candidates.append(value)
            for attr in ("id", "member_openid", "user_openid", "union_openid", "username"):
                value = getattr(mention, attr, None)
                if isinstance(value, str) and value:
                    candidates.append(value)
            if getattr(mention, "bot", False):
                flag_bot = True

        state = await self.group_bot_state(message.group_openid or "")
        bot_ids = {str(state.get("member_openid") or "")} | {str(v) for v in (state.get("_bot_ids") or [])}
        bot_ids = {value for value in bot_ids if value != ""}

        if bot_ids & set(candidates):
            return True
        if not bot_ids and flag_bot:
            # no id to compare against, but the mention is flagged as a bot
            return True
        log.info(
            "mention not for me (bot=%s seen=%s flags=%s)",
            ",".join(short_id(v) for v in list(bot_ids)[:3]) or "-",
            ",".join(short_id(v) for v in candidates[:5]) or "-",
            flag_bot,
        )
        return False

    async def group_bot_state(self, group_openid: str, *, force: bool = False) -> Dict[str, Any]:
        """機器人在该群的状态：消息范围、是否允许主动发言（缓存 60s）。"""
        cached = self.group_state.get(group_openid)
        if cached is not None and not force and time.time() - float(cached.get("_at", 0.0)) < 60.0:
            return cached
        try:
            state = await self.api.get_group_bot_state(group_openid)
        except Exception as error:  # noqa: BLE001 - capability may be gated
            log.info("group bot state unavailable: %s", error)
            return {}
        if not isinstance(state, dict):
            return {}
        state = dict(state)
        state["_at"] = time.time()
        self.group_state[group_openid] = state
        return state

    async def status_text(self, conv_key: str) -> str:
        """Human-facing summary of what the bot may do in this conversation."""
        kind, _, openid = conv_key.partition(":")
        lines = [f"**会话**：{self.conv_label(conv_key)}"]
        if kind == "group":
            state = await self.group_bot_state(openid)
            scope = str(state.get("recv_msg_setting") or "unknown")
            scope_text = {"all": "全量消息 ✅", "mention": "仅 @ 我", "unknown": "未知"}.get(scope, scope)
            proactive = state.get("allow_proactive_msg")
            proactive_text = "允许 ✅" if proactive is True else ("未开启" if proactive is False else "未知")
            lines.append(f"**消息范围**：{scope_text}")
            lines.append(f"**主动发言**：{proactive_text}")
            if state.get("joined_at"):
                lines.append(f"**入群时间**：{state['joined_at']}")
            bound = openid in self.state.group_owners
            lines.append(f"**群主绑定**：{'已绑定' if bound else '未绑定（群主可发 /绑定）'}")
        else:
            lines.append(f"**主人**：{'是' if openid == self.owner_openid else '不是'}")
        lines.append(f"**会话已绑定 DSH**：{'是' if conv_key in self.targets else '本次进程内未活动'}")
        return "\n".join(lines)

    async def _session_usage(self, session_id: str) -> Dict[str, Any]:
        """Run the Node usage reader; the Session log is multi-frame zstd."""
        node = shutil.which("node") or "node"
        script = ROOT / "usage.mjs"
        try:
            process = await asyncio.create_subprocess_exec(
                node,
                str(script),
                session_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
        except (OSError, asyncio.TimeoutError) as error:
            return {"ok": False, "error": str(error)}
        text = stdout.decode("utf-8", "replace").strip()
        try:
            return json.loads(text or "{}")
        except json.JSONDecodeError:
            detail = stderr.decode("utf-8", "replace").strip() or text
            return {"ok": False, "error": detail[:120]}

    @staticmethod
    def menu_text(help_body: str) -> str:
        """Short header for the command panel message."""
        return "**指令面板**\n点下面的按钮，或直接发指令。\n\n" + help_body

    @staticmethod
    def _usage_cost(stats: Dict[str, Any]) -> float:
        """Rough CNY estimate from the token mix (¥2/¥0.2/¥3 per 1M)."""
        return (
            int(stats.get("inputTokens") or 0) / 1e6 * 2
            + int(stats.get("cacheReadTokens") or 0) / 1e6 * 0.2
            + int(stats.get("outputTokens") or 0) / 1e6 * 3
        )

    async def usage_all_text(self, conv_key: str, bindings: Dict[str, Any]) -> str:
        """Recent Sessions, most expensive first, with the bound ones labelled."""
        stats = await self._session_usage("--all")
        if not stats.get("ok"):
            return f"读不到用量：{stats.get('error')}"
        sessions = stats.get("sessions") or []
        if not sessions:
            return "没有找到可统计的会话。"
        owners: Dict[str, str] = {}
        for key, value in bindings.get("bound") or []:
            owners[str(value)] = key
        sessions.sort(key=lambda row: int(row.get("totalTokens") or 0), reverse=True)
        lines = ["**最近会话 token 用量**", "| 会话 | 消息 | 合计 | 约¥ |", "|---|---|---|---|"]
        total_tokens = 0.0
        total_cost = 0.0
        for row in sessions[:10]:
            session_id = str(row.get("sessionId") or "")
            title = str(row.get("title") or session_id[:12]).strip() or session_id[:12]
            if len(title) > 14:
                title = title[:14] + "…"
            mark = "◆" if owners.get(session_id) == conv_key else ("·" if session_id in owners else " ")
            tokens = int(row.get("totalTokens") or 0)
            cost = self._usage_cost(row)
            total_tokens += tokens
            total_cost += cost
            lines.append(f"| {mark}{title} | {int(row.get('messages') or 0)} | {tokens:,} | {cost:.2f} |")
        lines.append(f"◆=本会话 · 共 {len(sessions)} 个会话，前 10 个合计 {int(total_tokens):,} token，约 ¥{total_cost:.2f}。")
        return "\n".join(lines)

    async def usage_text(self, conv_key: str, scope: str = "") -> str:
        """Token usage of the DSH Session bound to this conversation."""
        try:
            bindings = await self.bridge.sessions()
        except BridgeError as error:
            return f"拿不到会话绑定：{error}"
        if scope in {"全部", "所有", "all", "-a", "全", "all-sessions"}:
            return await self.usage_all_text(conv_key, bindings)
        session_id = ""
        for key, value in bindings.get("bound") or []:
            if key == conv_key:
                session_id = str(value)
                break
        if session_id == "":
            return "这个会话还没绑定 DSH，说句话让我建一个再看用量。"
        stats = await self._session_usage(session_id)
        if not stats.get("ok"):
            return f"读不到用量：{stats.get('error')}"
        input_tokens = int(stats.get("inputTokens") or 0)
        cache_read = int(stats.get("cacheReadTokens") or 0)
        output_tokens = int(stats.get("outputTokens") or 0)
        rows = [
            ("消息数", f"{int(stats.get('messages') or 0)}"),
            ("输入（未命中）", f"{input_tokens:,}"),
            ("缓存命中输入", f"{cache_read:,}"),
            ("输出", f"{output_tokens:,}"),
            ("合计", f"{int(stats.get('totalTokens') or 0):,}"),
        ]
        lines = ["**本会话 token 用量**", "| 项 | 值 |", "|---|---|"]
        lines += [f"| {name} | {value} |" for name, value in rows]
        prompt = input_tokens + cache_read
        hit_rate = (cache_read / prompt * 100) if prompt > 0 else 0.0
        cost = self._usage_cost(stats)
        model = ",".join(stats.get("models") or []) or "unknown"
        span = 0.0
        if stats.get("firstAt") and stats.get("lastAt"):
            span = (int(stats["lastAt"]) - int(stats["firstAt"])) / 60000
        lines.append(
            f"缓存命中 {hit_rate:.1f}%，约 ¥{cost:.2f}（¥2/M 未命中 · ¥0.2/M 命中 · ¥3/M 输出）；"
            f"模型 {model}，跨度 {span:.0f} 分钟。"
        )
        return "\n".join(lines)

    async def sessions_text(self, conv_key: str) -> str:
        """Human-readable view of the current binding and the switchable Sessions."""
        try:
            data = await self.bridge.sessions()
        except BridgeError as error:
            return f"取会话列表失败：{error}"
        lines: List[str] = ["**当前 QQ 会话绑定**"]
        for key, session_id in data.get("bound") or []:
            mark = "（本会话）" if key == conv_key else ""
            lines.append(f"· `{session_id}` ← {self.conv_label(key)}{mark}")
        for key, session_id in data.get("returns") or []:
            if key == conv_key:
                lines.append(f"**可切回**：`{session_id}`（发 /切回）")
        host = data.get("host") or {}
        rows = host.get("sessions") or []
        if rows:
            lines.append(f"**DSH 会话**（来源 {host.get('source')}）")
            for row in rows[:12]:
                title = (row.get("title") or "").strip()
                lines.append(f"· `{row.get('id')}` {title}".rstrip())
        elif host.get("source") == "unavailable":
            lines.append("（该 DSH 版本未暴露会话列表 API，可直接 /切会话 <session-id> 指定）")
        if host.get("error"):
            lines.append(f"（列表接口报错：{host['error']}）")
        lines.append("用法：/切会话 <session-id> 切过去，/切回 回到原来的会话。")
        return "\n".join(lines)

    async def handle_extra_command(self, conv_key: str, text: str, lowered: str, *, is_owner: bool = False) -> bool:
        """Shared /状态 /链接 /窗口 /撤回 handling; True when the message was a command."""
        head = lowered.split(" ", 1)[0]
        if not is_owner and (lowered in OWNER_ONLY_COMMANDS or head in OWNER_ONLY_COMMANDS):
            await self.send_text(conv_key, "这条指令只有主人能用。")
            return True
        if lowered in STATE_COMMANDS:
            await self.send_text(conv_key, await self.status_text(conv_key))
            return True
        if lowered in LINK_COMMANDS:
            await self.send_text(conv_key, f"机器人邀请链接：{await self.share_link()}")
            return True
        if lowered in WINDOW_COMMANDS and self.rt_bool("capture_enabled", True):
            ok, listing = await self._run_capture(["-List"])
            rows: List[str] = []
            for raw in listing.splitlines():
                parts = raw.split("\t")
                if len(parts) < 2:
                    continue
                title = parts[1].strip()
                if not title:
                    continue
                if len(title) > 34:
                    title = title[:34] + "…"
                rows.append(f"{len(rows) + 1}. {title}")
                if len(rows) >= 20:
                    break
            if rows:
                await self.send_text(conv_key, "当前可见窗口：\n" + "\n".join(rows))
            else:
                await self.send_text(conv_key, "没取到窗口列表")
            return True
        if lowered in MENU_COMMANDS:
            await self.send_text(conv_key, self.menu_text(self.help_text()), keyboard=command_keyboard())
            return True
        if lowered.split(" ", 1)[0] in USAGE_COMMANDS:
            parts = text.split(maxsplit=1)
            scope = parts[1].strip().lower() if len(parts) > 1 else ""
            await self.send_text(conv_key, await self.usage_text(conv_key, scope))
            return True
        if lowered in SESSION_COMMANDS:
            await self.send_text(conv_key, await self.sessions_text(conv_key))
            return True
        if lowered in BACK_COMMANDS:
            try:
                result = await self.bridge.switch_session(conv_key, "")
            except BridgeError as error:
                await self.send_text(conv_key, f"切回失败：{error}")
                return True
            await self.send_text(conv_key, f"已切回 `{result.get('sessionId')}`，消息重新进原会话。")
            return True
        if lowered.split(" ", 1)[0] in SWITCH_COMMANDS:
            parts = text.split(maxsplit=1)
            target = parts[1].strip() if len(parts) > 1 else ""
            if not target:
                await self.send_text(conv_key, "用法：/切会话 <session-id>\n先发 /会话 看有哪些可选。")
                return True
            try:
                result = await self.bridge.switch_session(conv_key, target)
            except BridgeError as error:
                await self.send_text(conv_key, f"切换失败：{error}")
                return True
            await self.send_text(
                conv_key,
                f"已切到 `{result.get('sessionId')}`；从现在起消息都进这个会话，\n要继续原来的工作发 /切回。",
            )
            return True
        if lowered.split(" ", 1)[0] in RECALL_COMMANDS:
            if not is_owner:
                await self.send_text(conv_key, "撤回只有主人能用。")
                return True
            await self._recall_command(conv_key, text)
            return True
        if lowered.split(" ", 1)[0] in POOL_COMMANDS:
            await self.send_text(conv_key, self._pool_text(conv_key))
            return True
        if (lowered in SHOT_COMMANDS or lowered.split(" ", 1)[0] in SHOT_COMMANDS) and self.rt_bool("capture_enabled", True):
            parts = text.split(maxsplit=1)
            wanted = parts[1].strip() if len(parts) > 1 else ""
            ok, detail = await self.capture_shot(wanted)
            if ok:
                await self.send_shot(conv_key, detail, f"📸 {wanted or '全屏'} · {Path(detail).name}")
            else:
                await self.send_text(conv_key, f"截图失败：{detail}")
            return True
        return False

    async def _run_capture(self, args: List[str], out: Optional[str] = None) -> Tuple[bool, str]:
        """Run tools/window-capture.ps1 and return (ok, captured path or message)."""
        command = [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(CAPTURE_SCRIPT), *args,
        ]
        if out is not None:
            command += ["-Out", out]
        try:
            process = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=45)
        except (OSError, asyncio.TimeoutError) as error:
            return False, f"截屏失败：{error}"
        text = (stdout or b"").decode("utf-8", "replace")
        detail = (stderr or b"").decode("utf-8", "replace").strip()
        for line in text.splitlines():
            if line.startswith("CAPTURED "):
                return True, line[len("CAPTURED "):].strip()
        return False, (detail or text).strip()[:300] or "截屏失败（没有输出）"

    async def capture_shot(self, target: str) -> Tuple[bool, str]:
        """Capture the screen (or a window matching `target`) into shots/."""
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
        name = f"shot-{time.strftime('%Y%m%d-%H%M%S')}.png"
        out = str(SHOT_DIR / name)
        wanted = target.strip()
        if wanted in {"", "全屏", "screen", "桌面"}:
            return await self._run_capture(["-FullScreen"], out)
        if wanted in {"前台", "foreground"}:
            return await self._run_capture(["-Foreground"], out)
        if wanted.isdigit():
            # /截图 9 = /窗口 列表里的第 9 个（用完整标题，不用展示用的截断标题）
            full = await self._window_title_by_index(int(wanted))
            if full is None:
                return False, f"没有第 {wanted} 个窗口（先发 /窗口 看列表）"
            wanted = full
        return await self._run_capture(["-Title", wanted], out)

    async def _window_title_by_index(self, index: int) -> Optional[str]:
        """Full title of the index-th visible window (1-based), as listed by -List."""
        ok, listing = await self._run_capture(["-List"])
        if not ok:
            return None
        titles = []
        for raw in listing.splitlines():
            parts = raw.split("\t")
            if len(parts) < 2:
                continue
            title = parts[1].strip()
            if title:
                titles.append(title)
        if index < 1 or index > len(titles):
            return None
        return titles[index - 1]

    async def send_shot(self, conv_key: str, path: str, caption: str = "") -> bool:
        target = self.targets.get(conv_key) or self._target_from_key(conv_key)
        if target is None:
            return False
        self.targets.setdefault(conv_key, target)
        if caption:
            await self.send_text(conv_key, caption)
        return await self._send_file(target, path)

    async def share_link(self) -> str:
        """平台生成的机器人分享/邀请链接（群主用它把机器人加进群）。"""
        try:
            payload = await self.api.create_url_link("qqbridge")
        except Exception as error:  # noqa: BLE001
            log.warning("create_url_link failed: %s", error)
            return f"取链接失败：{error}"
        url = ""
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, dict):
                url = str(data.get("url") or "")
            url = url or str(payload.get("url") or "")
        return url or f"平台没返回链接：{json.dumps(payload, ensure_ascii=False)[:200]}"

    async def _collect_images(
        self, attachments: Optional[List[Dict[str, Any]]]
    ) -> Tuple[List[Dict[str, str]], int]:
        """Download up to four QQ image attachments; returns (images, skipped)."""
        images: List[Dict[str, str]] = []
        skipped = 0
        for attachment in list(attachments or [])[:4]:
            url = attachment.get("url")
            if not url:
                skipped += 1
                continue
            image = await download_image(
                str(url),
                max_bytes=int(self.rt_float("image_max_mb", self.config.image_max_mb) * 1024 * 1024),
                dump_dir=str(SHOT_DIR / "incoming"),
            )
            if image is None:
                skipped += 1
                log.warning("image skipped (unreadable): %s", attachment.get("content_type"))
                continue
            images.append(image)
        return images, skipped

    # -- sending ------------------------------------------------------------ #
    async def send_text(self, conv_key: str, text: str, *, keyboard: Optional[Dict[str, Any]] = None) -> None:
        """Send text to one conversation, chunked and within QQ's reply limits."""
        target = self.targets.get(conv_key) or self._target_from_key(conv_key)
        if target is None:
            log.warning("cannot answer unknown conversation %r", conv_key)
            return
        if not looks_like_openid(target.openid):
            log.warning("skipping synthetic conversation %r", conv_key)
            return
        self.targets.setdefault(conv_key, target)
        if not self.rt_bool("enabled", True):
            log.info("master switch off; dropping reply to %s", conv_key)
            return
        if target.kind == "group" and not self.rt_bool("group_enabled", True):
            return
        if target.kind == "c2c" and not self.rt_bool("c2c_enabled", True):
            return
        if self._rate_limited(conv_key):
            return
        self._count_send(conv_key)
        now = time.time()
        last = self._last_sent.get(conv_key)
        if last is not None and last[0] == text and now - last[1] < 15:
            log.warning("skip duplicate send to %s (same text within %.0fs)", conv_key, now - last[1])
            return
        self._last_sent[conv_key] = (text, now)
        for index, chunk in enumerate(chunk_text(text, self.rt_int("max_chars", self.config.max_chars))):
            await self._send_chunk(target, chunk, keyboard=keyboard if index == 0 else None)

    async def _post(
        self,
        target: Target,
        chunk: str,
        *,
        keyboard: Optional[Dict[str, Any]],
        msg_id: Optional[str],
        markdown: bool,
    ) -> Any:
        self._msg_seq += 1
        payload: Dict[str, Any] = {"msg_seq": self._msg_seq}
        if msg_id:
            payload["msg_id"] = msg_id
        if keyboard is not None:
            payload["keyboard"] = keyboard
        if markdown:
            payload["msg_type"] = 2
            payload["markdown"] = {"content": chunk}
        else:
            payload["msg_type"] = 0
            payload["content"] = chunk
        if target.kind == "group":
            result = await self.api.post_group_message(group_openid=target.openid, **payload)
        else:
            result = await self.api.post_c2c_message(openid=target.openid, **payload)
        self._pool_sent(target, result, chunk)
        return result

    def _display_name(self, conv_key: str, member_openid: str) -> str:
        """How the model should see a group member: nickname when known, else 群友+短号."""
        tail = short_id(member_openid).upper()
        name = getattr(self, "_member_names", {}).get(conv_key, {}).get(tail, "")
        if name:
            return name
        try:
            saved = json.loads(MEMBERS_FILE.read_text(encoding="utf-8"))
            name = str(((saved.get(conv_key) or {}).get(tail) or {}).get("name") or "")
        except (OSError, ValueError):
            name = ""
        return name or ("群友" + tail)

    def _remember_member(self, conv_key: str, member_openid: str, nickname: str = "") -> None:
        """Index speakers (tail6 → openid + 昵称) and mirror it to disk for the panel/tools."""
        if not member_openid:
            return
        if not re.fullmatch(r"[0-9A-Fa-f]{32}", str(member_openid)):
            # 只认真实的 openid：测试桩/脏数据不允许污染 state/members.json
            return
        index = self.member_index.setdefault(conv_key, {})
        tail = short_id(member_openid).upper()
        index[tail] = member_openid
        if nickname:
            names = getattr(self, "_member_names", None)
            if names is None:
                names = self._member_names = {}
            names.setdefault(conv_key, {})[tail] = str(nickname)[:40]
        try:
            MEMBERS_FILE.parent.mkdir(parents=True, exist_ok=True)
            MEMBERS_FILE.write_text(
                json.dumps(
                    {
                        conv_key: {
                            tail: {
                                "openid": openid,
                                "name": getattr(self, "_member_names", {}).get(conv_key, {}).get(tail, ""),
                                "avatar": (
                                    f"https://q.qlogo.cn/qqapp/{self.config.appid}/{openid}/640"
                                    if getattr(self.config, "appid", "")
                                    else ""
                                ),
                                "last_seen": time.strftime("%Y-%m-%d %H:%M:%S"),
                            }
                            for tail, openid in self.member_index.get(conv_key, {}).items()
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except Exception as error:  # noqa: BLE001 - index is best-effort
            log.warning("member index persist failed: %s", error)

    def _readable_at(self, text: str, target: Optional[Target] = None) -> str:
        """Per QQ docs: 群聊 @人用 <qqbot-at-user id="member_openid"/>，仅 markdown 消息支持。"""
        if not text:
            return text
        text = text.replace("@全体", AT_EVERYONE_TOKEN).replace("@everyone", AT_EVERYONE_TOKEN)

        def alias(text_in: str) -> str:
            return OPENID_RE.sub(lambda match: "@群友" + match.group(1)[-6:].upper(), text_in)

        if target is None or target.kind != "group":
            return alias(text)
        known = self.member_index.get(target.conv_key) or {}
        if not known:
            return alias(text)

        def replace_guard(match: "_re.Match[str]") -> str:
            key = match.group(1).upper()
            openid = known.get(key)
            return f'<qqbot-at-user id="{openid}" />' if openid else match.group(0)

        return _AT_ALIAS_RE.sub(replace_guard, alias(text))

    async def _send_chunk(self, target: Target, chunk: str, *, keyboard: Optional[Dict[str, Any]]) -> None:
        # QQ renders 按钮 only under a Markdown message (msg_type=2) for group/
        # C2C chats, so a keyboard forces the markdown path.
        chunk = self._readable_at(chunk, target)
        md_auto = self.rt_bool("md_auto", self.config.md_auto)
        # @ 标签只有 markdown 消息支持（QQ 文档：文本交互 → 使用 @ 能力）
        wants_at = "<qqbot-at-" in chunk
        use_markdown = keyboard is not None or wants_at or (md_auto and looks_like_markdown(chunk))
        msg_id = target.passive_slot()
        try:
            await self._post(target, chunk, keyboard=keyboard, msg_id=msg_id, markdown=use_markdown)
            log.info(
                "sent %s (%d chars, %s) to %s",
                "markdown" if use_markdown else "text",
                len(chunk),
                "passive" if msg_id else "proactive",
                target.conv_key,
            )
            return
        except Exception as error:  # noqa: BLE001 - platform rejects many optional fields
            log.warning("send failed (%s): %s", type(error).__name__, error)
        if target.kind == "group":
            state = self.group_state.get(target.openid) or {}
            if state.get("allow_proactive_msg") is False:
                log.warning("skip proactive message: group %s does not allow it", target.conv_key)
                return
        try:
            await self._post(target, chunk, keyboard=None, msg_id=None, markdown=False)
        except Exception as error:  # noqa: BLE001 - nothing left to try
            log.error("proactive plain send failed (%s): %s", type(error).__name__, error)

    # -- outbound files ----------------------------------------------------- #
    def _allowed_file(self, path: str) -> Optional[str]:
        """Absolute path when it exists inside an allowed root, else None."""
        try:
            resolved = Path(path).expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            return None
        if not resolved.is_file():
            # 目录被当成文件上传时会抛 Errno 13（Permission denied），这里提前挡住
            return None
        roots = list(self.config.send_file_roots)
        # 自动分区工作区默认在别的盘（如 D:\dsh-qqbot-temp），必须一并放行，
        # 否则模型写在那里的图/文件会被"outside SEND_FILE_ROOTS"挡掉。
        extra = self.rt_str("auto_group_root", "").strip()
        if extra:
            roots.append(extra)
        for root in roots:
            try:
                resolved.relative_to(Path(root).resolve())
            except (OSError, ValueError):
                continue
            return str(resolved)
        return None

    def sticker_names(self) -> List[str]:
        """Available sticker file stems, for the prompt hint and lookup."""
        try:
            return sorted(
                path.stem
                for path in STICKER_DIR.iterdir()
                if path.suffix.lower() in {".png", ".gif", ".jpg", ".jpeg", ".webp"}
            )
        except OSError:
            return []

    def resolve_sticker(self, name: str) -> Optional[str]:
        wanted = name.strip().lower()
        for stem in self.sticker_names():
            if stem.lower() == wanted:
                for suffix in (".png", ".gif", ".jpg", ".jpeg", ".webp"):
                    candidate = STICKER_DIR / f"{stem}{suffix}"
                    if candidate.exists():
                        return str(candidate)
        return None

    def _persist_streams(self) -> None:
        """Remember open streams across restarts so a new process can close them."""
        try:
            payload = {
                conv: {k: s.get(k) for k in ("index", "msg_seq", "event_id", "stream_msg_id", "text")}
                for conv, s in self._streams.items()
                if s.get("stream_msg_id")
            }
            STREAMS_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except OSError as error:
            log.debug("stream state persist failed: %s", error)

    async def _close_stale_streams(self) -> None:
        """严格闭合：上个进程留下的流必须先关掉，否则新流会撞上“其它流式消息发送中”。"""
        try:
            stale = json.loads(STREAMS_FILE.read_text(encoding="utf-8")) if STREAMS_FILE.exists() else {}
        except (OSError, ValueError):
            stale = {}
        for conv_key, saved in list(stale.items()):
            if conv_key in self._streams or not saved.get("stream_msg_id"):
                continue
            self._streams[conv_key] = {**saved, "sent_text": saved.get("text", ""), "sent": 0, "last": 0.0, "turn_id": ""}
            log.info("closing stale stream left by a previous process (%s)", conv_key)
            await self._finish_stream(conv_key)
        if STREAMS_FILE.exists():
            try:
                STREAMS_FILE.unlink()
            except OSError:
                pass

    async def _finish_stream(self, conv_key: str) -> None:
        """Close an open streaming message so media never truncates it mid-frame."""
        state = self._streams.pop(conv_key, None)
        self._persist_streams()
        if state is None or int(state.get("index", 0)) == 0:
            return
        target = self.targets.get(conv_key) or self._target_from_key(conv_key)
        if target is None or not state.get("stream_msg_id"):
            return
        payload = {
            "input_mode": "replace",
            "input_state": 10,
            "content_type": "markdown",
            # 空内容收尾会被客户端显示成"该消息类型暂不支持查看"，给个占位
            "content_raw": STICKER_MARK.sub("", SEND_FILE_MARK.sub("", str(state.get("text") or ""))).strip() or "📎 文件在下面",
            "event_id": state.get("event_id") or target.last_msg_id or "",
            "msg_seq": state.get("msg_seq", 1),
            "index": int(state.get("index", 0)),
            "stream_msg_id": state["stream_msg_id"],
        }
        http = getattr(self.api, "_http", None)
        previous = getattr(http, "base_url", None)
        try:
            if previous:
                http.base_url = SG_GROUP_BASE_URL
            await self.api.post_c2c_stream_message(openid=target.openid, **payload)
        except Exception as error:  # noqa: BLE001 - never block media on a stream hiccup
            log.warning("stream finish failed (%s): %s", type(error).__name__, error)
        finally:
            if previous:
                http.base_url = previous
            self._persist_streams()

    async def _send_file(self, target: Target, path: str) -> bool:
        """Upload one local file into the conversation as a QQ media message."""
        file_type = FILE_TYPES.get(Path(path).suffix.lower(), 4)
        try:
            if target.kind == "group":
                result = await self.api.upload_group_media(
                    group_openid=target.openid, file_path=path, file_type=file_type, srv_send_msg=True
                )
            else:
                result = await self.api.upload_c2c_media(
                    user_openid=target.openid, file_path=path, file_type=file_type, srv_send_msg=True
                )
            self._pool_sent(target, result, f"[文件] {Path(path).name}")
        except Exception as error:  # noqa: BLE001 - platform rejects unsupported media
            log.warning("file send failed (%s, type=%s): %s", Path(path).name, file_type, error)
            return False
        self._bump("files_sent")
        self._bump("files_image" if file_type == 1 else "files_doc")
        self._timeline("file", Path(path).name)
        log.info("sent file %s (type=%s) to %s", Path(path).name, file_type, target.conv_key)
        return True

    def _spawn_files(self, conv_key: str, text: str) -> None:
        """Send media off the pull loop.

        The pull loop is the single reader of the bridge feed: a slow platform
        upload inside it froze every later event (DSH looked finished while QQ
        showed nothing). Uploads therefore run as background tasks.
        """
        if not (SEND_FILE_MARK.search(text) or STICKER_MARK.search(text)):
            return

        async def runner() -> None:
            try:
                await self._dispatch_files(conv_key, text)
            except Exception as error:  # noqa: BLE001 - never kill the loop
                log.exception("file dispatch failed: %s", error)

        task = asyncio.create_task(runner())
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _dispatch_files(self, conv_key: str, text: str) -> str:
        """Send [[send_file: path]] / [[sticker: name]] payloads, return the rest."""
        problems: List[str] = []
        stickers = [match.strip() for match in STICKER_MARK.findall(text)]
        if stickers:
            target = self.targets.get(conv_key) or self._target_from_key(conv_key)
            for name in stickers:
                resolved = self.resolve_sticker(name)
                if resolved is None:
                    log.warning("unknown sticker %r (have %s)", name, ",".join(self.sticker_names()[:8]))
                    problems.append(f"表情包「{name}」不存在")
                    continue
                if target is not None:
                    await self._send_file(target, resolved)
            text = STICKER_MARK.sub("", text).strip()
            if not text:
                return ""
        paths = [match.strip() for match in SEND_FILE_MARK.findall(text)]
        if not paths:
            return text
        target = self.targets.get(conv_key) or self._target_from_key(conv_key)
        if target is None:
            return SEND_FILE_MARK.sub("", text).strip()
        for path in paths:
            allowed = self._allowed_file(path)
            if allowed is None:
                # 不再静默：路径不存在或不在允许目录，都要让对话里的人知道
                log.warning("refusing to send %s (outside SEND_FILE_ROOTS)", path)
                candidate = Path(path).expanduser()
                if not candidate.exists():
                    reason = "文件不存在"
                elif candidate.is_dir():
                    reason = "这是个目录，不是文件"
                else:
                    reason = "路径不在允许目录内"
                problems.append(f"{candidate.name}：{reason}")
                continue
            sent = await self._send_file(target, allowed)
            if not sent:
                problems.append(f"{Path(allowed).name}：平台拒绝发送")
        if problems:
            await self.send_text(conv_key, "⚠ 有文件没发出去：" + "；".join(problems[:4]))
        return SEND_FILE_MARK.sub("", text).strip()

    # -- ack watchdog ------------------------------------------------------- #
    def _arm_ack(self, conv_key: str) -> None:
        if not self.rt_bool("ack_enabled", False):
            return
        self._cancel_ack(conv_key)
        ack_delay = self.rt_float("ack_delay_s", self.config.ack_delay_s)
        if ack_delay <= 0 or not self.config.ack_text:
            return

        async def later() -> None:
            try:
                await asyncio.sleep(ack_delay)
            except asyncio.CancelledError:
                return
            await self.send_text(conv_key, self.config.ack_text)

        self._acks[conv_key] = asyncio.create_task(later())

    def _cancel_ack(self, conv_key: str) -> None:
        task = self._acks.pop(conv_key, None)
        if task is not None and not task.done():
            task.cancel()

    # -- DSH ---------------------------------------------------------------- #
    def _release_if_stuck(self, conv_key: str, *, force: bool = False) -> None:
        """A turn that never returns must not silence the conversation forever.

        Note: this must NOT depend on ack_enabled — the "还在处理" placeholder is
        optional, but the dead-man release is the only thing that unblocks a
        conversation whose turn/end event was lost (e.g. the bridge dropped).
        """
        if self._inflight.get(conv_key, 0) <= 0:
            return
        started = self._inflight_at.get(conv_key, 0.0)
        waited = time.time() - started if started > 0 else 0.0
        if not force and waited < self.rt_float("stuck_turn_s", self.config.stuck_turn_s):
            return
        log.warning("turn in %s stuck for %.0fs; releasing the queue", conv_key, waited)
        self._inflight[conv_key] = 0
        self._inflight_at.pop(conv_key, None)
        if conv_key in self.queued:
            asyncio.create_task(self._drain_queued(conv_key))

    def _message_idx(self, message):
        """The msg_idx QQ assigned to this very message (needed to resolve quotes)."""
        raw = getattr(message, "raw", None) or {}
        scene = raw.get("message_scene") if isinstance(raw, dict) else None
        return _scene_ext(scene).get("msg_idx", "")

    async def _quote_images(self, quote: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
        """Download the quoted image(s) so the model can actually see them."""
        if not quote or quote.get("kind") != "image":
            return []
        urls = [url for url in (quote.get("urls") or []) if isinstance(url, str) and url]
        if not urls:
            return []
        images, _skipped = await self._collect_images([{"url": url} for url in urls])
        return list(images)

    def _quote_author(self, ref_idx):
        """Who wrote the quoted message: the bot itself, the owner, or a group member."""
        message_id = self.pool_idx.get(ref_idx, "")
        item = self.pool.get(message_id) if message_id else None
        if item is None or item.at < time.time() - self._pool_ttl():
            return "", False
        if item.outbound:
            return "你自己（机器人）", True
        return item.author or "群友", False

    def _quote_of(self, message):
        """Body + author + kind of the quoted message.

        QQ ships the quoted element in raw["msg_elements"] ({"content": ...,
        "message_type": 103, "msg_idx": ...}); the author is resolved from the
        recent pool by that msg_idx. Text is the only kind QQ always fills in,
        so media quotes degrade to a labelled placeholder instead of fiction.
        """
        if not self.rt_bool("quote_enabled", True):
            return None
        raw = getattr(message, "raw", None) or {}
        if not isinstance(raw, dict):
            return None

        kind = "text"
        text = ""
        ref_idx = ""
        quote_urls = []
        elements = raw.get("msg_elements")
        if isinstance(elements, list):
            for element in elements:
                if not isinstance(element, dict):
                    continue
                ref_idx = str(element.get("msg_idx") or "")
                content = element.get("content")
                if isinstance(content, str) and content.strip():
                    text = content.strip()
                    kind = "text"
                    break
                name = element.get("file_name") or element.get("filename") or ""
                attachments = element.get("attachments")
                if isinstance(name, str) and name.strip():
                    text = name.strip()
                    kind = "file"
                    break
                if isinstance(attachments, list) and attachments:
                    text = ""
                    kind = "image"
                    urls = [_attachment_url(item) for item in attachments]
                    quote_urls = [url for url in urls if url][:4]
                    break
                single = _attachment_url(element)
                if single:  # 有的版本把图片地址直接放在元素上
                    text = ""
                    kind = "image"
                    quote_urls = [single]
                    break
                if ref_idx:
                    kind = "other"
                    break

        if self.rt_bool("quote_probe", False) and not text:
            reference = raw.get("message_reference")
            log.info("quote probe (c2c): keys=%s reference=%r",
                     ",".join(sorted(raw.keys())) if isinstance(raw, dict) else "-",
                     reference)

        # Private chats carry the quote as message_reference instead of msg_elements.
        if kind == "text" and not text:
            reference = raw.get("message_reference")
            if isinstance(reference, dict):
                content = reference.get("content")
                ref_id = str(reference.get("message_id") or reference.get("id") or "")
                if isinstance(content, str) and content.strip():
                    text = content.strip()
                if ref_id:
                    item = self.pool.get(ref_id)
                    if item is not None and item.at >= time.time() - self._pool_ttl():
                        return {
                            "ref_id": ref_id,
                            "resolved": True,
                            "author": "你自己（机器人）" if item.outbound else (item.author or "对方"),
                            "text": text or item.text,
                            "outbound": bool(item.outbound),
                            "kind": "text",
                        }
                    if text:
                        return {
                            "ref_id": ref_id,
                            "resolved": True,
                            "author": "",
                            "text": text,
                            "outbound": False,
                            "kind": "text",
                        }
                elif text:
                    return {"ref_id": "", "resolved": True, "author": "", "text": text, "outbound": False, "kind": "text"}

        if kind == "text" and not text:
            flat = _scene_ext(raw.get("message_scene"))
            ref_idx = flat.get("ref_msg_idx", "") or ref_idx
            if not ref_idx:
                return None
            author, outbound = self._quote_author(ref_idx)
            message_id = self.pool_idx.get(ref_idx, "")
            item = self.pool.get(message_id) if message_id else None
            if item is None or item.at < time.time() - self._pool_ttl():
                return {"ref_id": ref_idx, "resolved": False, "author": author, "text": "", "kind": "text"}
            return {
                "ref_id": ref_idx,
                "resolved": True,
                "author": author,
                "text": item.text,
                "outbound": outbound,
                "kind": "text",
            }

        if not ref_idx and kind == "text" and not text:
            return None
        if not ref_idx:
            return None

        if self.rt_bool("quote_probe", False):
            log.info("quote element: kind=%s len=%d ref=%s", kind, len(text), short_id(ref_idx))
        author, outbound = self._quote_author(ref_idx)
        return {
            "ref_id": ref_idx,
            "resolved": True,
            "author": author,
            "text": text,
            "outbound": outbound,
            "kind": kind,
            "urls": list(quote_urls),
        }

    def _merge_queued(self, conv_key: str, text: str, images: List[Dict[str, str]], sender_name: str, is_owner: bool, chime: bool, chat: bool = False) -> None:
        """One conversation runs one turn at a time; later messages wait here."""
        entry = self.queued.get(conv_key)
        if entry is None:
            entry = QueuedPrompt()
            self.queued[conv_key] = entry
        if text.strip():
            entry.parts.append(text)
        entry.images.extend(images)
        entry.sender_name = sender_name
        entry.is_owner = is_owner or entry.is_owner
        entry.chime = entry.chime and chime
        entry.chat = entry.chat and chat if entry.parts[:-1] else chat
        log.info("queued behind running turn in %s (%d part(s))", conv_key, len(entry.parts))

    async def _drain_queued(self, conv_key: str) -> None:
        """Send the merged backlog once the running turn has finished."""
        entry = self.queued.pop(conv_key, None)
        if entry is None:
            return
        age = time.time() - entry.first_at
        if age > self.config.stale_prompt_s:
            log.info("dropping %.0fs-old backlog in %s to avoid a stale answer", age, conv_key)
            return
        text = "\n".join(part for part in entry.parts if part.strip())
        await self._submit(conv_key, text, entry.sender_name, entry.is_owner, entry.images, chime=entry.chime, chat=entry.chat)

    async def _submit(
        self,
        conv_key: str,
        text: str,
        sender_name: str,
        is_owner: bool,
        images: Optional[List[Dict[str, str]]] = None,
        *,
        chime: bool = False,
        chat: bool = False,
    ) -> None:
        self._release_if_stuck(conv_key)
        if self._inflight.get(conv_key, 0) > 0 or conv_key in self.queued:
            self._merge_queued(conv_key, text, images or [], sender_name, is_owner, chime, chat)
            return
        quote = self._pending_quotes.pop(conv_key, None)
        recent = self.recent_images.pop(conv_key, None)
        if recent is not None and time.time() - recent[1] < self.rt_float("image_cache_s", 120) and not images:
            images = recent[0]
        stickers = self.sticker_names()
        if stickers and text.strip():
            text = text + "\n（想发个表情包时，单独一行写 [[sticker: 名字]]，可选：" + ",".join(stickers[:12]) + "）"
        if chat and text.strip():
            # 长度与"别复述过程"由插件侧的群聊指令负责，这里只补一条不重复的话
            text = "【闲聊模式】不要调用工具。" + chr(10) + text
        self._chat_turns[conv_key] = bool(chat)
        try:
            await self.bridge.inbound(
                conv_key=conv_key,
                text=text,
                sender_name=sender_name,
                is_owner=is_owner,
                approval_target=self._owner_conv(),
                images=images,
                chime=chime,
                quote=quote,
                auto_group=self.rt_bool("auto_group", True),
                auto_group_root=self.rt_str("auto_group_root", ""),
            )
        except BridgeError as error:
            log.error("inbound failed: %s", error)
            await self.send_text(conv_key, f"DSH 桥接不可用：{error}")
            return
        self._submitted_at[conv_key] = time.time()
        self._inflight[conv_key] = self._inflight.get(conv_key, 0) + 1
        self._inflight_at[conv_key] = time.time()
        if not chime:
            self._arm_ack(conv_key)

    async def _buffer_context(self, conv_key: str, text: str, sender_name: str) -> None:
        """Disabled on purpose: replaying chatter into every prompt bloated the
        Session history until the model call 400'd. The judge batch carries the
        context instead, so nothing is forwarded here."""
        return

    # -- debounce: several consecutive messages become one prompt ----------- #
    async def _queue_message(
        self,
        conv_key: str,
        text: str,
        sender_name: str,
        is_owner: bool,
        images: List[Dict[str, str]],
        *,
        chat: bool = False,
        quote: Optional[Dict[str, Any]] = None,
    ) -> None:
        if quote:
            self._pending_quotes[conv_key] = quote
        entry = self.pending.get(conv_key)
        if entry is None:
            entry = Pending()
            self.pending[conv_key] = entry
        if text.strip():
            entry.parts.append(text)
        entry.images.extend(images)
        entry.sender_name = sender_name
        entry.is_owner = is_owner
        entry.chat = entry.chat and chat if entry.parts[:-1] else chat
        if entry.job is not None and not entry.job.done():
            entry.job.cancel()
        entry.job = asyncio.create_task(self._flush(conv_key))

    async def _flush(self, conv_key: str) -> None:
        entry = self.pending.get(conv_key)
        if entry is None:
            return
        wait = min(self.config.debounce_s, max(0.05, self.config.debounce_max_s - (time.time() - entry.started)))
        try:
            await asyncio.sleep(wait)
        except asyncio.CancelledError:
            return
        entry = self.pending.pop(conv_key, None)
        if entry is None:
            return
        text = "\n".join(part for part in entry.parts if part.strip())
        if not text and not entry.images:
            return
        await self._submit(conv_key, text, entry.sender_name, entry.is_owner, entry.images, chat=entry.chat)

    # -- event feed --------------------------------------------------------- #
    def _load_cursor(self) -> Optional[int]:
        """Resume the bridge event feed where the previous process stopped.

        Replies produced while the bot was restarting stay in the plugin's ring
        buffer, so reloading the cursor delivers them instead of dropping them.
        """
        try:
            return int(CURSOR_FILE.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    def _save_cursor(self, cursor: Optional[int]) -> None:
        if cursor is None:
            return
        try:
            CURSOR_FILE.parent.mkdir(parents=True, exist_ok=True)
            CURSOR_FILE.write_text(str(cursor), encoding="utf-8")
        except OSError:
            pass

    METRIC_KEYS = (
        "c2c_msgs", "group_msgs", "group_at", "group_images", "quotes",
        "judge_calls", "judge_spoke", "judge_silent", "hook_skips",
        "streams", "stream_fallbacks", "files_image", "files_doc", "files_sent",
        "approvals", "approvals_allow", "approvals_deny",
        "questions", "questions_answered", "question_timeouts",
        "mutes", "unmutes", "kicks", "errors",
    )

    def _bump(self, name: str, n: int = 1) -> None:
        """Cheap counters for the dashboard; never allowed to break a handler."""
        if not hasattr(self, "_metrics"):
            self._metrics = {key: 0 for key in self.METRIC_KEYS}
            self._metrics_at = 0.0
        self._metrics[name] = int(self._metrics.get(name, 0)) + n
        now = time.time()
        if n:
            bucket = int(now // 60) * 60
            series = getattr(self, "_series", None)
            if series is None:
                series = self._series = {}
            cell = series.setdefault(bucket, {})
            cell[name] = int(cell.get(name, 0)) + n
            cutoff = now - 180 * 60
            for stale in [key for key in series if key < cutoff]:
                series.pop(stale, None)
        self._archive_complete_minutes(now)
        if now - float(getattr(self, "_metrics_at", 0.0)) < 3.0:
            return
        self._metrics_at = now
        self._write_metrics()

    def _write_metrics(self) -> None:
        """Persist counters/series/timeline; the file's started_at always tracks the live process."""
        try:
            METRICS_FILE.write_text(
                json.dumps(
                    {
                        "started_at": getattr(self, "_started_at", 0.0),
                        **self._metrics,
                        "series": getattr(self, "_series", {}),
                        "events": getattr(self, "_events", []),
                        "runtime": {
                            "inflight": sum(int(v) for v in getattr(self, "_inflight", {}).values()),
                            "queued": len(getattr(self, "queued", {}) or {}),
                            "chatter": sum(len(getattr(entry, "lines", [])) for entry in (getattr(self, "chatter", {}) or {}).values()),
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _read_recent_archive(self, now: float, window_s: float = 180 * 60) -> Dict[int, Dict[str, int]]:
        """Finished minutes from the per-day JSONL files inside the window."""
        rows: Dict[int, Dict[str, int]] = {}
        for offset in (0, 1):  # 跨零点时补上前一天
            day = time.strftime("%Y-%m-%d", time.localtime(now - offset * 86400))
            path = METRICS_DIR / f"{day}.jsonl"
            if not path.exists():
                continue
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    bucket = int(row.pop("minute"))
                    if now - bucket > window_s:
                        continue
                    rows[bucket] = {key: int(value) for key, value in row.items()}
            except (OSError, ValueError) as error:
                log.debug("metrics archive read failed (%s): %s", day, error)
        return rows

    def _seed_metrics(self) -> None:
        """Everything except uptime is time-based: counters, per-minute series and the timeline all survive a restart."""
        try:
            saved = json.loads(METRICS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        now = time.time()
        archived = self._read_recent_archive(now)
        totals: Dict[str, int] = {key: 0 for key in self.METRIC_KEYS}
        for cell in archived.values():
            for key, value in cell.items():
                if key in totals:
                    totals[key] += value
        # metrics.json 是绝对总数，JSONL 是逐分钟明细；取较大值，免得被节流丢掉的最后几秒把总数拉低
        self._metrics = {
            key: max(int(saved.get(key, 0) or 0), totals.get(key, 0)) for key in self.METRIC_KEYS
        }
        self._metrics_at = 0.0
        series: Dict[int, Dict[str, int]] = dict(archived)
        saved_series = saved.get("series")
        if isinstance(saved_series, dict):
            for bucket, cell in saved_series.items():
                try:
                    key = int(bucket)
                except (TypeError, ValueError):
                    continue
                if now - key > 180 * 60 or not isinstance(cell, dict):
                    continue
                series.setdefault(key, {name: int(value) for name, value in cell.items()})
        self._series = series
        self._archived = set(archived)
        events = saved.get("events")
        if isinstance(events, list):
            self._events = events[-20:]
        if saved.get("scale"):
            self._lifecycle = str(saved.get("scale"))
        self._write_metrics()  # 启动即刷新 started_at，面板的运行时长不必等第一条消息

    def _archive_complete_minutes(self, now: float) -> None:
        """Append each finished minute to a per-day JSONL so history outlives a restart."""
        series = getattr(self, "_series", None)
        if not series:
            return
        written = getattr(self, "_archived", None)
        if written is None:
            written = self._archived = set()
        current = int(now // 60) * 60
        try:
            METRICS_DIR.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        for bucket in sorted(series):
            if bucket >= current or bucket in written:
                continue
            cell = series[bucket]
            day = time.strftime("%Y-%m-%d", time.localtime(bucket))
            line = json.dumps({"minute": int(bucket), **{k: int(v) for k, v in cell.items()}}, ensure_ascii=False)
            try:
                with (METRICS_DIR / f"{day}.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(line + chr(10))
            except OSError as error:
                log.debug("metrics archive failed: %s", error)
                continue
            written.add(bucket)
        if len(written) > 2000:
            self._archived = set(sorted(written)[-500:])
        self._prune_metrics(now)

    def _prune_metrics(self, now: float) -> None:
        """Keep at most metrics_keep_days of archive; prune once per day."""
        keep_days = max(1, self.rt_int("metrics_keep_days", 30))
        last = float(getattr(self, "_pruned_at", 0.0))
        if now - last < 3600:
            return
        self._pruned_at = now
        cutoff = now - keep_days * 86400
        removed = 0
        try:
            for path in METRICS_DIR.glob("*.jsonl"):
                try:
                    day_start = time.mktime(time.strptime(path.stem, "%Y-%m-%d"))
                except ValueError:
                    continue
                if day_start < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
            for path in LOG_DIR.glob("*.log.*"):
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink(missing_ok=True)
                        removed += 1
                except OSError:
                    continue
        except OSError as error:
            log.debug("metrics prune failed: %s", error)
            return
        if removed:
            log.info("pruned %d old metric/log file(s) (keep %d days)", removed, keep_days)

    def _timeline(self, kind: str, text: str) -> None:
        """Last few interesting things, for the dashboard timeline."""
        if not hasattr(self, "_events"):
            self._events = []
        self._events.append({"at": time.time(), "kind": kind, "text": str(text)[:120]})
        if len(self._events) > 20:
            self._events = self._events[-20:]

    def _note_owner_activity(self, conv_key: str, is_owner: bool) -> None:
        """Group-admin tools are owner-only: remember who spoke last in this conversation."""
        if not hasattr(self, "_owner_recent"):
            self._owner_recent = {}
        self._owner_recent[conv_key] = time.time() if is_owner else 0.0

    def _admin_allowed(self, payload: Dict[str, Any]) -> Tuple[bool, str]:
        """A tool call may act only when the owner is the one who just asked."""
        conv_key = str(payload.get("convKey") or "")
        group = str(payload.get("group") or "")
        if conv_key.startswith("c2c:"):
            return (conv_key == self._owner_conv(), "只有主人能使用群管理功能")
        if conv_key and conv_key != f"group:{group}":
            return (False, "会话与目标群不一致")
        last = getattr(self, "_owner_recent", {}).get(conv_key, 0.0)
        if last <= 0 or time.time() - last > self.rt_float("admin_owner_window_s", 300):
            return (False, "只有主人能使用群管理功能（最近没有主人的指令）")
        return (True, "")

    async def _admin_loop(self) -> None:
        """Execute group-admin requests queued by the panel/tools (mute / kick / members)."""
        outbox = STATE_DIR / "admin"
        while True:
            try:
                if outbox.is_dir():
                    for path in sorted(outbox.glob("*.json")):
                        payload = {}
                        try:
                            payload = json.loads(path.read_text(encoding="utf-8"))
                        except (OSError, ValueError):
                            path.unlink(missing_ok=True)
                            continue
                        if payload.get("status") not in (None, "pending"):
                            continue
                        result = {"status": "done", "ok": False, "error": "unknown action"}
                        try:
                            action = str(payload.get("action") or "")
                            if action in ("group", "muted", "member", "stats"):
                                result = await self._info_action(action, payload)
                                path.write_text(json.dumps({**payload, **result}, ensure_ascii=False), encoding="utf-8")
                                continue
                            allowed, why = self._admin_allowed(payload)
                            if not allowed:
                                log.warning("admin %s refused: %s", action, why)
                                path.write_text(
                                    json.dumps({**payload, "status": "done", "ok": False, "error": why}, ensure_ascii=False),
                                    encoding="utf-8",
                                )
                                continue
                            if (
                                action == "kick"
                                and not payload.get("confirmed")
                                and self.rt_bool("kick_confirm", True)
                            ):
                                if not payload.get("id"):
                                    payload["id"] = uuid.uuid4().hex[:12]
                                # 踢人不可逆：先到主人私聊要一次二次确认
                                request_id = str(payload.get("id") or "")
                                payload["_path"] = str(path)
                                self._admin_confirm[request_id] = dict(payload)
                                target_group = str(payload.get("group") or "")
                                target_member = str(payload.get("member") or "")
                                who = self._display_name(f"group:{target_group}", target_member)
                                group_label = await self._group_name(target_group) or ("…" + target_group[-6:])
                                await self.send_text(
                                    self._owner_conv(),
                                    "⚠ 请求踢人" + chr(10)
                                    + "群：" + group_label + chr(10)
                                    + "成员：" + who
                                    + ("" if not who.startswith("群友") else "（昵称未知，这是短号）") + chr(10)
                                    + "点下面的按钮确认，取消则不动。",
                                    keyboard=kick_confirm_keyboard(request_id),
                                )
                                path.write_text(
                                    json.dumps({**payload, "status": "waiting"}, ensure_ascii=False),
                                    encoding="utf-8",
                                )
                                continue
                            group = str(payload.get("group") or "")
                            member = str(payload.get("member") or "")
                            if action == "mute" and group and member:
                                raw_seconds = payload.get("seconds")
                                # 注意：0 是「解禁」，不能被 or 600 吞成 10 分钟
                                seconds = 600 if raw_seconds is None else int(raw_seconds)
                                # 官方字段：op=add/del + mute_expire_at（RFC3339，带时区）
                                entry: Dict[str, Any] = {"op": "add" if seconds > 0 else "del", "member_openid": member}
                                if seconds > 0:
                                    expire = time.time() + seconds
                                    entry["mute_expire_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(expire)) + "+08:00"
                                await self.api.set_group_restrict_chat_setting(group_openid=group, members=[entry])
                                still_muted = None
                                try:
                                    state_now = await self.api.get_group_restrict_chat_setting(group_openid=group)
                                    still_muted = any(
                                        str(item.get("member_openid")) == member
                                        for item in (state_now.get("members") or [])
                                    )
                                except Exception as error:  # noqa: BLE001 - state re-read is best effort
                                    log.warning("mute state re-read failed: %s", error)
                                result = {
                                    "status": "done",
                                    "ok": True,
                                    "group_name": await self._group_name(group),
                                    "member_name": self._display_name(f"group:{group}", member),
                                    "seconds": seconds,
                                    "op": entry["op"],
                                    "still_muted": still_muted,
                                }
                                self._bump("unmutes" if entry["op"] == "del" else "mutes")
                                self._timeline("admin", f'mute {entry["op"]} {seconds}s')
                            elif action == "kick" and group and member:
                                await self.api.batch_remove_group_members(
                                    group_openid=group,
                                    member_openids=[member],
                                    add_to_member_blacklist=bool(payload.get("blacklist")),
                                )
                                result = {"status": "done", "ok": True}
                                self._bump("kicks")
                                self._timeline("admin", "kick")
                            elif action == "mute_state" and group:
                                state = await self.api.get_group_restrict_chat_setting(group_openid=group)
                                result = {"status": "done", "ok": True, "state": state}
                            elif action == "members":
                                result = {"status": "done", "ok": True, "members": payload.get("known") or {}}
                        except Exception as error:  # noqa: BLE001 - report the platform message verbatim
                            self._bump("errors")
                            result = {"status": "done", "ok": False, "error": str(error)}
                        try:
                            path.write_text(json.dumps({**payload, **result}, ensure_ascii=False), encoding="utf-8")
                        except OSError:
                            pass
                        log.info("admin %s -> %s", payload.get("action"), "ok" if result.get("ok") else result.get("error"))
            except Exception as error:  # noqa: BLE001
                log.warning("admin loop error: %s", error)
            await asyncio.sleep(0.8)

    async def _question_loop(self) -> None:
        """Poll the file outbox the panel writes; render each dsh question as a keyboard."""
        outbox = STATE_DIR / "questions"
        while True:
            try:
                if outbox.is_dir():
                    for path in sorted(outbox.glob("*.json")):
                        try:
                            payload = json.loads(path.read_text(encoding="utf-8"))
                        except (OSError, ValueError):
                            path.unlink(missing_ok=True)
                            continue
                        conv_key = str(payload.get("convKey") or "")
                        question_id = str(payload.get("id") or "")
                        text = str(payload.get("question") or "")
                        options = [str(item) for item in (payload.get("options") or [])]
                        if conv_key and question_id and options:
                            body = "**需要你确认**" + chr(10) + chr(10) + text + chr(10) + chr(10)
                            body += chr(10).join(f"{i + 1}. {label}" for i, label in enumerate(options))
                            self._bump("questions")
                            self._timeline("question", question_id[:8])
                            await self.send_text(conv_key, body, keyboard=question_keyboard(question_id, options))
                            log.info("question %s delivered to %s", short_id(question_id), conv_key)
                        path.unlink(missing_ok=True)
            except Exception as error:  # noqa: BLE001 - never let the watcher die
                log.warning("question loop error: %s", error)
            await asyncio.sleep(1.0)

    async def _pull_loop(self) -> None:
        cursor = self._load_cursor()
        if cursor is not None:
            log.info("resuming bridge feed from cursor %s", cursor)
        while True:
            _heartbeat()
            try:
                result = await asyncio.wait_for(
                    self.bridge.pull(cursor, self.config.pull_wait_ms),
                    timeout=(self.config.pull_wait_ms / 1000.0) + 20,
                )
                head = result.get("cursor", cursor)
                events = result.get("events") or []
                if isinstance(head, int) and isinstance(cursor, int) and head < cursor:
                    # The plugin reloaded and its sequence restarted: everything in
                    # this response belongs to the old ring buffer, so jumping to
                    # the new head avoids re-sending replies that already went out.
                    log.warning("bridge sequence reset (%s -> %s); skipping backlog", cursor, head)
                    cursor = head
                    self._save_cursor(cursor)
                    continue
                cursor = head
                self._save_cursor(cursor)
                _heartbeat()
                for event in events:
                    if event.get("type") in URGENT_EVENTS:
                        # Approvals must never queue behind a slow reply send: a
                        # stuck turn used to swallow the whole approval card.
                        task = asyncio.create_task(self._handle_urgent(event))
                        self._urgent_tasks.add(task)
                        task.add_done_callback(self._urgent_tasks.discard)
                        continue
                    self._pull_failures = 0
                    await self._handle_event(event)
            except asyncio.CancelledError:
                log.warning("pull loop cancelled; watchdog will restart it")
                return
            except BridgeError as error:
                self._pull_failures = getattr(self, "_pull_failures", 0) + 1
                log.warning("bridge pull failed (%d in a row): %s", self._pull_failures, error)
                if self._pull_failures >= 3:
                    # 桥接掉线期间丢掉的 turn/end 会让会话永远"忙"，这里强制解锁
                    for key in list(self._inflight):
                        self._release_if_stuck(key, force=True)
                    self._pull_failures = 0
                await asyncio.sleep(3)
            except Exception as error:  # noqa: BLE001 - keep the feed alive
                self._bump("errors")
                log.exception("pull loop error: %s", error)
                await asyncio.sleep(3)

    async def _pull_watchdog(self) -> None:
        """Keep the event feed alive: restart it whenever the task dies."""
        while True:
            await asyncio.sleep(10)
            task = getattr(self, "_pull_task", None)
            if task is None or task.done():
                reason = "missing" if task is None else ("cancelled" if task.cancelled() else str(task.exception()))
                log.warning("pull loop down (%s); restarting", reason)
                self._pull_task = asyncio.create_task(self._pull_loop())

    async def _handle_urgent(self, event: Dict[str, Any]) -> None:
        """Deliver an approval/notice out of band; one failure must not kill the feed."""
        try:
            await self._handle_event(event)
        except Exception as error:  # noqa: BLE001 - keep the pull loop alive
            log.exception("urgent event failed (%s): %s", event.get("type"), error)

    async def _handle_event(self, event: Dict[str, Any]) -> None:
        kind = event.get("type")
        conv_key = str(event.get("convKey") or "")
        if kind == "reply":
            self._cancel_ack(conv_key)
            text = str(event.get("text") or "").strip()
            tools = event.get("tools") or []
            reason = reason_text(event.get("reason"))
            # Turn bookkeeping happens on every path: a suppressed reply used to
            # leak the in-flight counter, so later messages queued forever.
            self._inflight[conv_key] = max(0, self._inflight.get(conv_key, 1) - 1)
            if conv_key in self._streams:
                # 回合结束了但流还开着（final 事件丢失/异常路径）：这里必须闭合，
                # 否则下一个回合会撞上"其它流式消息发送中"。
                try:
                    await self._close_stream(conv_key)
                except Exception as error:  # noqa: BLE001 - sealing is best effort
                    log.warning("stream seal on turn end failed: %s", error)
            started = self._submitted_at.pop(conv_key, None)
            turn_id = str(event.get("turnId") or "")
            duplicated = False
            if turn_id:
                duplicated = self._streamed_turns.pop(turn_id, None) is not None
            else:
                duplicated = conv_key in self._suppress_reply
                self._suppress_reply.discard(conv_key)
            if duplicated:
                log.info("turn %s already streamed; dropping durable duplicate for %s", turn_id or "-", conv_key)
                await self._drain_queued(conv_key)
                return
            if NO_REPLY_MARK in text:
                if self._chat_turns.pop(conv_key, False):
                    self._bump("judge_silent")
                    log.info("agent stayed silent in %s (chatter judge)", conv_key)
                    await self._drain_queued(conv_key)
                    return
                # A real question (@ or private chat) must never be answered with silence.
                log.warning("model tried to stay silent on a directed message in %s; answering instead", conv_key)
                text = text.replace(NO_REPLY_MARK, "").strip() or "在的，你说。"
            if self._chat_turns.pop(conv_key, False):
                self._bump("judge_spoke")
            had_media = bool(SEND_FILE_MARK.search(text) or STICKER_MARK.search(text))
            self._spawn_files(conv_key, text)
            text = STICKER_MARK.sub("", SEND_FILE_MARK.sub("", text)).strip()
            if had_media and not text:
                # 文件本身就是这轮的全部内容，不必再说"没有文字输出"
                await self._drain_queued(conv_key)
                return
            if not text:
                used = f"（调用了 {len(tools)} 个工具：{'、'.join(tools[:8])}）" if tools else ""
                text = f"（本轮结束 {reason or 'done'}，没有文字输出）{used}"
            if started is not None:
                log.info(
                    "reply latency %.2fs for %s (tools=%d, reason=%s)",
                    time.time() - started,
                    conv_key,
                    len(tools),
                    reason or "-",
                )
            await self.send_text(conv_key, text)
            self._bot_spoke_at[conv_key] = time.time()
            await self._drain_queued(conv_key)

        if kind == "stream":
            await self._handle_stream(event)
            return
        if kind == "approval":
            await self._deliver_approval(event)
            return
        if kind == "notice":
            await self.send_text(str(event.get("target") or conv_key), str(event.get("text") or ""))
            return

    def _stream_degraded(self, conv_key: str) -> bool:
        until = getattr(self, "_stream_holdoff", {}).get(conv_key, 0.0)
        return until > time.time()

    def _hold_stream(self, conv_key: str, why: str) -> None:
        if not hasattr(self, "_stream_holdoff"):
            self._stream_holdoff = {}
        hold = self.rt_float("stream_retry_s", 120)
        self._stream_holdoff[conv_key] = time.time() + hold
        log.warning("streaming suspended in %s for %.0fs: %s", conv_key, hold, why)

    def _new_stream_state(self, conv_key: str, target: Target, turn_id: str) -> Dict[str, Any]:
        self._msg_seq += 1
        return {
            "index": 0,
            "text": "",
            "sent_text": "",
            "last": 0.0,
            "msg_seq": self._msg_seq,
            "event_id": target.last_msg_id or "",
            "stream_msg_id": "",
            "turn_id": turn_id,
        }

    async def _stream_post(self, target: Target, state: Dict[str, Any], done: bool) -> bool:
        """One frame. index is allocated strictly increasing, only after a success."""
        body = STICKER_MARK.sub("", SEND_FILE_MARK.sub("", str(state.get("text") or ""))).strip()
        if not body:
            return True
        payload: Dict[str, Any] = {
            "input_mode": "replace",
            "input_state": 10 if done else 1,
            "content_type": "markdown",
            "content_raw": body,
            "event_id": state["event_id"],
            "msg_seq": int(state["msg_seq"]),
            "index": int(state["index"]),
        }
        if target.last_msg_id:
            payload["msg_id"] = target.last_msg_id
        if state.get("stream_msg_id"):
            payload["stream_msg_id"] = state["stream_msg_id"]
        http = getattr(self.api, "_http", None)
        previous = getattr(http, "base_url", None)
        try:
            if previous:
                # stream_messages lives on the sgroup host; the SDK default
                # (api.bot.qq.com) answers 50015001 "系统繁忙" for it.
                http.base_url = SG_GROUP_BASE_URL
            response = await self.api.post_c2c_stream_message(openid=target.openid, **payload)
        except Exception as error:  # noqa: BLE001 - a refused frame must never lose the answer
            message = str(error)
            log.warning("stream frame failed (%s): %s", type(error).__name__, message)
            if "其它流式消息发送中" in message or "引导已经结束" in message:
                self._hold_stream(target.conv_key, "platform reports another open stream")
            return False
        finally:
            if previous:
                http.base_url = previous
        if isinstance(response, dict) and response.get("id") and not state.get("stream_msg_id"):
            state["stream_msg_id"] = response["id"]
        state["index"] = int(state["index"]) + 1
        state["sent_text"] = state["text"]
        state["last"] = time.time()
        self._persist_streams()
        return True

    async def _close_stream(self, conv_key: str) -> bool:
        """Strictly seal the open stream: exactly one final frame, then forget it."""
        state = self._streams.pop(conv_key, None)
        self._persist_streams()
        if state is None or not state.get("stream_msg_id"):
            return True
        target = self.targets.get(conv_key) or self._target_from_key(conv_key)
        if target is None:
            return True
        return await self._stream_post(target, state, True)

    async def _handle_stream(self, event: Dict[str, Any]) -> None:
        """Progressive C2C delivery with a strict one-open-stream contract.

        The platform allows a single open stream per user, requires index to
        increase per frame, and refuses anything after input_state 10. So: one
        session per turn, frames serialised per conversation, a guaranteed seal
        on the final event, and a plain-message fallback when the platform
        refuses - never a silently lost answer.
        """
        conv_key = str(event.get("convKey") or "")
        target = self.targets.get(conv_key) or self._target_from_key(conv_key)
        if target is None or target.kind != "c2c":
            return
        if not self.rt_bool("stream_enabled", False):
            return
        final = bool(event.get("final"))
        delta = str(event.get("text") or "")
        turn_id = str(event.get("turnId") or "")
        if final and turn_id and turn_id in self._streamed_turns:
            # 同一回合的收尾事件重投：这条回答已经流式送出去了，别再开一个新气泡
            log.info("duplicate final stream event for turn %s ignored", turn_id)
            self._streams.pop(conv_key, None)
            self._persist_streams()
            return
        if not hasattr(self, "_stream_locks"):
            self._stream_locks = {}
        lock = self._stream_locks.setdefault(conv_key, asyncio.Lock())
        async with lock:
            if self._stream_degraded(conv_key):
                if final and delta.strip():
                    await self.send_text(conv_key, STICKER_MARK.sub("", SEND_FILE_MARK.sub("", delta)).strip())
                    self._spawn_files(conv_key, delta)
                return
            state = self._streams.get(conv_key)
            if state is None:
                self._bump("streams")
                state = self._new_stream_state(conv_key, target, str(event.get("turnId") or ""))
                self._streams[conv_key] = state
            if delta:
                if final:
                    # 最终事件可能是「整段文本」（deltas 已经逐段流过），也可能只是最后一片。
                    # 整段时必须以它替换，叠加会让同一段话在气泡里重复两三遍。
                    streamed = str(state["text"]).rstrip()
                    incoming = delta.rstrip()
                    if not streamed or incoming.startswith(streamed) or streamed in incoming:
                        state["text"] = delta
                    elif streamed.endswith(incoming):
                        state["text"] = streamed
                    else:
                        state["text"] = streamed + delta
                else:
                    state["text"] += delta
            if not str(state["text"]).strip():
                if final:
                    self._streams.pop(conv_key, None)
                    self._persist_streams()
                return
            if final:
                ok = await self._close_stream(conv_key)
                fallback_sent = False
                if not ok:
                    fallback = STICKER_MARK.sub("", SEND_FILE_MARK.sub("", str(state.get("text") or ""))).strip()
                    if fallback and int(state.get("index", 0)) > 0:
                        self._bump("stream_fallbacks")
                        log.warning("stream unusable for %s; falling back to a plain message", conv_key)
                        await self.send_text(conv_key, fallback)
                        fallback_sent = True
                # delivered 决定要不要抑制 durable 回复：什么都没送出去时必须让它照常发，
                # 否则这条回答就凭空消失了。
                delivered = int(state.get("index", 0)) > 0 or fallback_sent
                if delivered:
                    self._spawn_files(conv_key, str(state.get("text") or ""))
                    if state.get("turn_id"):
                        self._streamed_turns[str(state["turn_id"])] = time.time()
                        if len(self._streamed_turns) > 50:
                            for stale in sorted(self._streamed_turns, key=self._streamed_turns.get)[:10]:
                                self._streamed_turns.pop(stale, None)
                    else:
                        self._suppress_reply.add(conv_key)
                if ok:
                    log.info("stream finished (%d chars, %d frame(s)) for %s", len(state["text"]), state["index"], conv_key)
                return
            interval = self.rt_float("stream_interval_ms", 300) / 1000.0
            if time.time() - float(state["last"]) < interval:
                return
            if state["sent_text"] == state["text"]:
                return
            if not await self._stream_post(target, state, False):
                # A refused frame makes the session untrustworthy: drop it and let
                # the durable reply carry the answer as one plain message.
                self._streams.pop(conv_key, None)
                self._persist_streams()
    async def _deliver_approval(self, event: Dict[str, Any]) -> None:
        """Send the approval card (buttons + fallback text) to the owner chat."""
        approval_id = str(event.get("approvalId") or "")
        if not approval_id:
            return
        target_key = str(event.get("target") or event.get("convKey") or "")
        if target_key == "":
            return
        tool_name = str(event.get("toolName") or "unknown")
        reason = reason_text(event.get("reason")).strip()
        arguments = str(event.get("argumentPreview") or "").strip()
        self.pending_approvals[approval_id] = event
        self._cancel_ack(str(event.get("convKey") or ""))
        body = ["**⚠️ DSH 需要你授权一次操作**", "", f"> 工具：\u0060{tool_name}\u0060"]
        if arguments:
            body.append(f"> 参数：\u0060{arguments}\u0060")
        if reason:
            body.append(f"> 理由：{reason}")
        body.append(f"> 来源：{self.conv_label(str(event.get('convKey') or ''))}")
        body.append("")
        body.append("点下面的 **允许 / 拒绝** 按钮，或直接回复「允许」/「拒绝」；超时按拒绝。")
        self._bump("approvals")
        log.info("delivering approval %s (%s) to %s", approval_id[:8], tool_name, target_key)
        await self.send_text(target_key, "\n".join(body), keyboard=approval_keyboard(approval_id))

    def _spawn_approval(self, conv_key: str, decision: str, approval_id: str) -> None:
        """Run the decision off the interaction handler, but never let it die silently."""
        async def runner() -> None:
            try:
                await self._resolve_approval(conv_key, decision, approval_id)
            except Exception as error:  # noqa: BLE001 - the click must still be acked
                log.exception("approval resolve failed (%s): %s", decision, error)

        task = asyncio.create_task(runner())
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _resolve_kick_confirm(self, interaction: Interaction, request_id: str, approved: bool) -> None:
        """Owner-only second confirmation for an irreversible kick."""
        await self._interaction_result(interaction, 0)
        payload = self._admin_confirm.pop(request_id, None)
        if payload is None:
            await self.send_text(self._owner_conv(), "这条踢人请求已经处理过了")
            return
        group = str(payload.get("group") or "")
        member = str(payload.get("member") or "")
        who = self._display_name(f"group:{group}", member)
        result_path = str(payload.pop("_path", "") or "")
        ok, failure = False, None
        if not approved:
            await self.send_text(self._owner_conv(), "已取消：没有踢出 " + who)
            failure = "cancelled by owner"
        else:
            try:
                await self.api.batch_remove_group_members(
                    group_openid=group, member_openids=[member], add_to_member_blacklist=bool(payload.get("blacklist"))
                )
                ok = True
                await self.send_text(self._owner_conv(), "✅ 已踢出 " + who)
            except Exception as error:  # noqa: BLE001 - report platform refusal to the owner
                failure = str(error)
                await self.send_text(self._owner_conv(), f"❌ 踢人失败：{failure}")
        if result_path:
            try:
                Path(result_path).write_text(
                    json.dumps({**payload, "status": "done", "ok": ok, "error": failure}, ensure_ascii=False),
                    encoding="utf-8",
                )
            except OSError as error:
                log.warning("kick result write failed: %s", error)

    async def _resolve_approval(self, conv_key: str, decision: str, approval_id: Optional[str]) -> None:
        if not self.owner_openid:
            await self.send_text(conv_key, "还没认领主人，无法审批。")
            return
        chosen = approval_id if approval_id in self.pending_approvals else None
        if chosen is None:
            chosen = next(reversed(self.pending_approvals), None) if self.pending_approvals else None
        if chosen is None:
            await self.send_text(conv_key, "现在没有待审批的操作。")
            return
        outcome = self.pending_approvals.pop(chosen, None) or {}
        tool_name = str(outcome.get("toolName") or "")
        try:
            await self.bridge.approve(chosen, decision)
        except BridgeError as error:
            await self.send_text(conv_key, f"审批没能送达 DSH：{error}")
            return
        self._decided[chosen] = decision
        self._bump("approvals_allow" if decision == "allow" else "approvals_deny")
        self._timeline("approval", f"{tool_name or 'tool'} -> {decision}")
        while len(self._decided) > 100:
            self._decided.pop(next(iter(self._decided)), None)
        label = ("✅ 已允许" if decision == "allow" else "⛔ 已拒绝") + (f"（{tool_name}）" if tool_name else "")
        tail = "，继续执行。" if decision == "allow" else "，本轮操作不会执行。"
        if not self.rt_bool("approval_inline_redraw", True):
            # 旧行为：结论文字 + 重发的「已处理」卡片（按钮已失效，再点只回 toast）
            await self.send_text(
                conv_key,
                label + tail,
                keyboard=decided_keyboard(chosen, label),
            )
        # 关闭时什么都不发：按钮已被 visited_label 就地重绘成「✓ 已允许 / ✓ 已拒绝」

    async def _buffer_chatter(self, conv_key: str, sender: str, text: str) -> None:
        """Collect group chatter; a judge run decides later whether to join in."""
        entry = self.chatter.get(conv_key)
        if entry is None:
            entry = Chatter()
            self.chatter[conv_key] = entry
        if text.lstrip().startswith(("【闲聊模式】", "【群聊插话判断】")):
            log.warning("dropped prompt-shaped chatter line")
            return
        entry.lines.append(f"[{time.strftime('%H:%M')}] {sender}: {text}")
        if len(entry.lines) > 12:
            entry.lines = entry.lines[-12:]
        if entry.first_at == 0.0:
            entry.first_at = time.time()
        if entry.timer is None or entry.timer.done():
            entry.timer = asyncio.create_task(self._judge_later(conv_key))

    async def _judge_later(self, conv_key: str) -> None:
        """Fire the judgment when the buffered window tops out, even if quiet."""
        entry = self.chatter.get(conv_key)
        if entry is None:
            return
        deadline = max(0.5, self.rt_float("chatter_max_s", self.config.chatter_max_s) - (time.time() - entry.first_at))
        try:
            await asyncio.sleep(deadline)
        except asyncio.CancelledError:
            return
        await self._maybe_judge(conv_key, force_timer=True)

    async def _prefetch_group_profiles(self) -> None:
        """Warm the group profile cache so cards and the panel have names immediately."""
        known: set = set()
        try:
            saved = json.loads(GROUPS_FILE.read_text(encoding="utf-8")) if GROUPS_FILE.exists() else {}
            if isinstance(saved, dict):
                known.update(key for key in saved if len(key) >= 20)
        except (OSError, ValueError):
            pass
        try:
            members = json.loads(MEMBERS_FILE.read_text(encoding="utf-8"))
            if isinstance(members, dict):
                known.update(key[6:] for key in members if key.startswith("group:"))
        except (OSError, ValueError):
            pass
        for group_openid in list(known)[:10]:
            try:
                await self._group_name(group_openid)
            except Exception as error:  # noqa: BLE001 - cosmetics only
                log.debug("group profile prefetch failed: %s", error)

    async def _info_action(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Read-only lookups for the model's tools (no owner gate needed)."""
        group = str(payload.get("group") or "")
        if action == "group":
            info: Dict[str, Any] = {}
            try:
                info = await self.api.get_group_info(group_openid=group)
                self._save_group_profile(group, info or {})
            except Exception as error:  # noqa: BLE001 - fall back to the cached profile
                log.info("group info lookup failed: %s", error)
            mute_rule = {}
            try:
                mute_rule = await self.api.get_group_restrict_chat_setting(group_openid=group)
            except Exception as error:  # noqa: BLE001 - optional detail
                log.info("group mute rule lookup failed: %s", error)
            saved = {}
            try:
                all_groups = json.loads(GROUPS_FILE.read_text(encoding="utf-8")) if GROUPS_FILE.exists() else {}
                saved = all_groups.get(group, {}) if isinstance(all_groups, dict) else {}
            except (OSError, ValueError):
                saved = {}
            return {
                "status": "done",
                "ok": bool(info or saved),
                "group": {
                    "openid": group,
                    "name": (info or {}).get("group_name") or saved.get("name") or "",
                    "memo": (info or {}).get("group_finger_memo") or saved.get("memo") or "",
                    "class": (info or {}).get("group_class_text") or saved.get("class") or "",
                    "tags": (info or {}).get("group_tags") or saved.get("tags") or [],
                    "members": (info or {}).get("group_member_num") or saved.get("members") or 0,
                },
                "mute_rule": mute_rule,
                "known_members": len(self.member_index.get(f"group:{group}", {})),
            }
        if action == "muted":
            try:
                state = await self.api.get_group_restrict_chat_setting(group_openid=group)
            except Exception as error:  # noqa: BLE001 - report the platform message
                return {"status": "done", "ok": False, "error": str(error)}
            members = []
            for item in state.get("members") or []:
                openid = str(item.get("member_openid") or "")
                members.append({
                    "name": item.get("username") or self._display_name(f"group:{group}", openid),
                    "openid": openid,
                    "short": short_id(openid).upper(),
                    "expire_at": item.get("mute_expire_at") or "",
                })
            return {"status": "done", "ok": True, "muted": members, "count": len(members)}
        if action == "member":
            member = str(payload.get("member") or "")
            conv = f"group:{group}"
            name = self._display_name(conv, member)
            entry: Dict[str, Any] = {}
            try:
                known = json.loads(MEMBERS_FILE.read_text(encoding="utf-8")) if MEMBERS_FILE.exists() else {}
                entry = ((known or {}).get(conv) or {}).get(short_id(member).upper(), {})
            except (OSError, ValueError):
                entry = {}
            muted = None
            try:
                state = await self.api.get_group_restrict_chat_setting(group_openid=group)
                for item in state.get("members") or []:
                    if str(item.get("member_openid")) == member:
                        muted = item.get("mute_expire_at") or ""
            except Exception:  # noqa: BLE001 - optional
                muted = None
            return {
                "status": "done",
                "ok": True,
                "member": {
                    "name": name,
                    "openid": member,
                    "short": short_id(member).upper(),
                    "avatar": entry.get("avatar") or f"https://q.qlogo.cn/qqapp/{self.config.appid}/{member}/640",
                    "last_seen": entry.get("last_seen") or "",
                    "muted_until": muted,
                },
            }
        if action == "stats":
            metrics = {}
            try:
                metrics = json.loads(METRICS_FILE.read_text(encoding="utf-8")) if METRICS_FILE.exists() else {}
            except (OSError, ValueError):
                metrics = {}
            counters = {key: int(metrics.get(key, 0) or 0) for key in self.METRIC_KEYS}
            return {"status": "done", "ok": True, "counters": counters, "events": (metrics.get("events") or [])[-5:]}
        return {"status": "done", "ok": False, "error": f"unknown info action: {action}"}

    def _save_group_profile(self, group_openid: str, info: Dict[str, Any]) -> None:
        """Keep the last known profile per group so the panel needs no API call."""
        try:
            saved = json.loads(GROUPS_FILE.read_text(encoding="utf-8")) if GROUPS_FILE.exists() else {}
        except (OSError, ValueError):
            saved = {}
        if not isinstance(saved, dict):
            saved = {}
        saved[group_openid] = {
            "name": str(info.get("group_name") or ""),
            "memo": str(info.get("group_finger_memo") or ""),
            "class": str(info.get("group_class_text") or ""),
            "tags": list(info.get("group_tags") or []),
            "members": int(info.get("group_member_num") or 0),
            "fetched_at": int(time.time()),
        }
        try:
            GROUPS_FILE.parent.mkdir(parents=True, exist_ok=True)
            GROUPS_FILE.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
        except OSError as error:
            log.debug("group profile save failed: %s", error)

    async def _group_name(self, group_openid: str) -> str:
        """Group display name, cached for 5 minutes and mirrored to state/groups.json."""
        if not group_openid:
            return ""
        cached = getattr(self, "_group_cache", None)
        if cached is None:
            cached = self._group_cache = {}
        entry = cached.get(group_openid)
        if entry and time.time() - entry[0] < 300:
            return entry[1]
        try:
            info = await self.api.get_group_info(group_openid=group_openid)
            name = str((info or {}).get("group_name") or "")
            cached[group_openid] = (time.time(), name)
            self._save_group_profile(group_openid, info or {})
            return name
        except Exception as error:  # noqa: BLE001 - naming is cosmetic
            log.debug("group info unavailable: %s", error)
            return entry[1] if entry else ""

    def _owner_label(self, conv_key: str, member_openid: str) -> str:
        """Owner tag with the nickname attached when we know it: 主人（𝒟𝒶𝒾𝓈𝓎）."""
        nick = self._display_name(conv_key, member_openid) if member_openid else ""
        if nick and not nick.startswith("群友"):
            return f"主人（{nick}）"
        return "主人"

    def _last_speaker_name(self, conv_key: str, lines: List[str]) -> str:
        """Resolve the newest buffered speaker ('[10:00] 名字: 内容') back to a nickname."""
        for line in reversed(lines or []):
            body = str(line)
            if "]" in body:
                body = body.split("]", 1)[1].strip()
            name = body.split(":", 1)[0].strip()
            if not name:
                continue
            tail = name.upper().replace("群友", "")
            openid = self.member_index.get(conv_key, {}).get(tail, "")
            return self._display_name(conv_key, openid) if openid else name
        return "群友"

    def _interject_hook(self, conv_key: str, lines: List[str]) -> bool:
        """Cheap pre-check: is this batch worth one model call at all?"""
        if not lines:
            return False
        text = chr(10).join(lines)
        if self.addresses_bot(text):
            return True
        if "?" in text or "？" in text:
            return True
        lowered = text.lower()
        for name in ("大肥鱼", "机器人", "dsh", "鱼"):
            if name in lowered:
                return True
        last = getattr(self, "_last_group_at", {}).get(conv_key, 0.0)
        cold = self.rt_float("interject_cold_s", 1200)
        if last and time.time() - last > cold:
            return True
        return False

    async def _maybe_judge(self, conv_key: str, *, force_timer: bool = False) -> None:
        """Ask the agent whether it wants to say something; it may stay silent."""
        entry = self.chatter.get(conv_key)
        if entry is None or not entry.lines:
            return
        if self._inflight.get(conv_key, 0) > 0 or conv_key in self.queued:
            return
        if self._in_quiet_hours():
            return
        now = time.time()
        if self.rt_bool("interject_hook_only", True) and not self._interject_hook(conv_key, entry.lines):
            # 没有钩子就不花一次模型调用；消息继续攒在缓冲里，等下一个钩子一起判
            entry.last_judge_at = now
            self._bump("hook_skips")
            log.info("chatter skipped (no hook) in %s", conv_key)
            return
        if now - entry.last_judge_at < self.rt_float("chatter_cooldown_s", self.config.chatter_cooldown_s):
            return
        if not force_timer and len(entry.lines) < self.rt_int("chatter_batch", self.config.chatter_batch):
            return
        lines = list(entry.lines)

        # Someone naming the bot inside plain chatter must get a real answer:
        # the judge prompt offers [NO_REPLY], and a called bot must not take it.
        if any(self.addresses_bot(line) for line in lines):
            self.chatter.pop(conv_key, None)
            joined = chr(10).join(line.split(": ", 1)[-1] for line in lines)
            log.info("chatter named the bot; answering instead of judging (%d line(s))", len(lines))
            await self._submit(conv_key, joined, self._last_speaker_name(conv_key, lines), False, None, chat=False)
            return

        entry.lines.clear()
        entry.first_at = 0.0
        entry.last_judge_at = now
        spoke_text, spoke_at = self._last_bot_say.get(conv_key, ("", 0.0))
        since = time.time() - spoke_at if spoke_text else float("inf")
        if spoke_text and since < self.rt_float("bot_say_memory_s", self.config.bot_say_memory_s):
            situation = (
                f"你在群里最近说过（{max(0, int(since))} 秒前）：\u201c{spoke_text[:160]}\u201d"
                f"（可参考的记录：最近 {int(self._pool_ttl() // 60)} 分钟 / 最近 {self._pool_limit()} 条）"
            )
        elif spoke_text:
            situation = (
                f"你在这群里已经安静了 {int(since // 60)} 分钟，最近没说话"
                f"（更早之前说过：\u201c{spoke_text[:80]}\u201d，只作背景，别重复它）。"
            )
        else:
            situation = (
                f"在最近 {int(self._pool_ttl() // 60)} 分钟 / 最近 {self._pool_limit()} 条消息的记录里，"
                "没看到你在群里说过话（不代表你从没说过，只是这些记录里没有）。"
            )
        speakers = [line.split(": ", 1)[0] for line in lines if ": " in line]
        last_speaker = speakers[-1] if speakers else "群友"
        prev_speaker = speakers[-2] if len(speakers) > 1 else ""
        last_text = lines[-1].split(": ", 1)[-1] if lines else ""
        called = self.addresses_bot(last_text)
        speakers = []
        for item in lines:
            # 行形如 "[14:11] 群友35DB11: 下午好啊"——先去时间戳，再取发言人
            body = str(item)
            if body.startswith("[") and "]" in body:
                body = body.split("]", 1)[1].strip()
            name = body.split(":", 1)[0].strip()
            if name and name not in speakers:
                speakers.append(name)
        recent = "、".join(speakers[:6]) or last_speaker
        if called:
            audience = f"最后一句来自 {last_speaker}，里面叫了你的名字（别名：{self._alias_list()}），是在跟你说话。"
        else:
            audience = (
                f"最近 {len(lines)} 条里发言的人：{recent}。最后一句来自 {last_speaker}。"
                "（谁在跟谁说话、是不是在问你，你自己按上下文判断，不要只看最后两条。）"
            )

        prompt = chr(10).join(
            [
                "【群聊插话判断】",
                situation,
                audience,
                "",
                "这之后群里在聊：",
                *lines,
                "",
                "像群里的一员那样判断——没人点名不代表你必须沉默：",
                f"- 想说话就说：有人叫你/别名（{self._alias_list()}）、问到你了、聊到你熟的或感兴趣的事、想吐槽想接梗想补充，都可以正常参与；",
                "- 不想说就不说：别人在互相对话、话题你没兴趣、或者你刚说过类似的话，只回 [NO_REPLY]；",
                "- 别人互相聊的时候，别把他们的话当成对你的邀请，也不要替他们回答；想参与就说得轻一点；",
                "- 不要重复自己说过的内容，不要总结/复述别人的聊天，不要客套，不要写成报告。",
            ]
        )
        self._bump("judge_calls")
        self._timeline("judge", f"{len(lines)} 行")
        log.info("judging %d line(s) of chatter in %s", len(lines), conv_key)
        await self._submit(conv_key, prompt, "群友", False, None, chat=True)

    def _pool_transcript(self, conv_key: str, limit: int = 12) -> str:
        """Recent messages of this conversation, verbatim, oldest first."""
        cutoff = time.time() - self._pool_ttl()
        items = [
            item
            for item in self.pool.values()
            if item.conv_key == conv_key and item.at >= cutoff
        ]
        items.sort(key=lambda item: item.at)
        lines = []
        for item in items[-limit:]:
            body = str(item.text)
            # 双保险：无论污染从哪条路径进来，提示词形状的文本都不许出现在聊天记录里
            if "【闲聊模式】" in body or "【群聊插话判断】" in body:
                continue
            if item.outbound:
                who = "你（机器人）"
            else:
                # 池里存的是短号，提示词里换成昵称（群友不知道自己的短号）
                tail = str(item.author or "").upper()
                openid = self.member_index.get(conv_key, {}).get(tail, "")
                who = self._display_name(conv_key, openid) if openid else item.author
            lines.append(f"[{time.strftime('%H:%M', time.localtime(item.at))}] {who}: {body}")
        return chr(10).join(lines)

    async def _plan_b(self, conv_key: str, message: Any, member_openid: str) -> None:
        """Plan B: an independent judge decides, then the main model gets the verbatim pool."""
        # 只有"未被点名"的闲聊才会走到这里（被 @ 的走 _handle_group_at），
        # 所以静默时段在这里拦，@ 与私聊不受影响。
        if self._in_quiet_hours():
            log.info("plan B skipped: quiet hours (%s)", self.rt_str("quiet_hours", ""))
            return
        transcript = self._pool_transcript(conv_key)
        if transcript.strip() == "":
            transcript = f"{self._display_name(conv_key, member_openid)}: {clean_content(getattr(message, 'content', ''))}"
        try:
            verdict = await self.bridge.judge(conv_key, transcript)
        except BridgeError as error:
            log.warning("plan B judge unavailable (%s); fallback to plain chatter", error)
            await self._buffer_chatter(conv_key, self._display_name(conv_key, member_openid), clean_content(getattr(message, "content", "")))
            await self._maybe_judge(conv_key)
            return
        need_reply = bool(verdict.get("needReply"))
        self._bump("judge_calls")
        self._bump("judge_spoke" if need_reply else "judge_silent")
        note = str(verdict.get("note") or "").strip()
        if not need_reply:
            log.info("plan B: judge stayed silent%s", f" ({note[:60]})" if note else "")
            try:
                await self.bridge.inbound(conv_key=conv_key, text=transcript, context_only=True)
            except BridgeError as error:
                log.debug("plan B context push failed: %s", error)
            return
        log.info("plan B: judge wants a reply%s", f" ({note[:60]})" if note else "")
        prompt = "【群里最近的原文】" + chr(10) + transcript
        if note:
            prompt += chr(10) + chr(10) + "【判断参考】" + note
        await self._queue_message(
            conv_key,
            prompt,
            self._display_name(conv_key, member_openid),
            False,
            [],
            chat=False,
        )

    async def _handle_group_at(self, message: GroupMessage, *, chat: bool = False) -> None:
        self._remember_id(message.id)
        log.info(
            "group @ from %s: %r",
            short_id(((message.author.member_openid if message.author else "") or "")),
            clean_content(message.content)[:120],
        )
        if not self.config.groups_enabled or not self.rt_bool("group_enabled", True) or not self.rt_bool("enabled", True):
            return
        group_openid = message.group_openid or ""
        conv_key = f"group:{group_openid}"
        member_openid = ""
        if message.author is not None:
            member_openid = message.author.member_openid or message.author.user_openid or ""
        text = clean_content(message.content)
        self._bump("group_at")
        if member_openid:
            self._remember_member(conv_key, member_openid, _author_nick(message))
        if getattr(message, "attachments", None):
            self._bump("group_images")
        self._pool_incoming(message, "group", group_openid, conv_key, short_id(member_openid))
        if member_openid:
            self.member_index.setdefault(conv_key, {})[short_id(member_openid).upper()] = member_openid
        is_owner = self._is_owner_group(group_openid, member_openid)
        self._note_owner_activity(conv_key, is_owner)
        if not hasattr(self, "_last_group_at"):
            self._last_group_at = {}
        self._last_group_at[conv_key] = time.time()
        if not is_owner and member_openid:
            is_owner = await self._bind_group_owner_by_role(group_openid, member_openid)
        lowered = text.lower()

        if text in BIND_COMMANDS:
            if not is_owner:
                await self.send_text(conv_key, "只有机器人主人才能绑定群主。")
                return
            self.state.group_owners[group_openid] = member_openid
            self.state.save()
            log.info("group owner bound: %s -> %s", group_openid, short_id(member_openid))
            await self.send_text(conv_key, "已把当前群里的你绑定为主人。")
            return
        if lowered in RESET_COMMANDS:
            if not is_owner:
                await self.send_text(conv_key, "这条指令只有主人能用。")
                return
            try:
                await self.bridge.reset(conv_key)
            except BridgeError as error:
                await self.send_text(conv_key, f"重置失败：{error}")
                return
            await self.send_text(conv_key, "已开新会话，上下文清空。")
            return
        if lowered in HELP_COMMANDS:
            await self.send_text(conv_key, self.help_text())
            return
        if lowered in ("/分组", "/workspace", "/ws"):
            try:
                result = await self.bridge.rebind(conv_key)
            except BridgeError as error:
                await self.send_text(conv_key, "创建分组失败：" + str(error))
                return
            if result.get("ok") and result.get("moved"):
                sandbox = result.get("sandbox")
                granted = ""
                if isinstance(sandbox, dict) and str(sandbox.get("granted") or "") == "failed":
                    granted = chr(10) + "⚠ 沙箱预授权失败：" + str(sandbox.get("reason") or "未知原因")
                await self.send_text(conv_key, "已迁移到工作区（上下文保留）：" + str(result.get("cwd")) + granted)
            elif result.get("ok"):
                reason = str(result.get("fallbackReason") or "")
                await self.send_text(conv_key, "已切到独立工作区：" + str(result.get("cwd")) + chr(10) + "方式：新建会话（上下文不继承）" + (("，原因：" + reason) if reason else ""))
            else:
                await self.send_text(conv_key, "创建分组失败：" + str(result.get("error")))
            return
        if lowered in ("/指令", "/commands"):
            try:
                result = await self.bridge.commands(conv_key)
            except BridgeError as error:
                await self.send_text(conv_key, "查询指令失败：" + str(error))
                return
            if not result.get("ok"):
                await self.send_text(conv_key, str(result.get("error") or "不可用"))
                return
            items = result.get("commands") or []
            lines = ["DSH 指令（实时，" + str(len(items)) + " 条）："]
            for item in items[:40]:
                desc = str(item.get("description") or "")
                lines.append("- /" + str(item.get("name")) + ((" — " + desc) if desc else ""))
            if len(items) > 40:
                lines.append("… 还有 " + str(len(items) - 40) + " 条")
            lines.append("")
            lines.append("直接用 /<名字> 就能执行（转给 DSH 官方命令通道）")
            await self.send_text(conv_key, chr(10).join(lines))
            return
        if lowered.startswith("/") and lowered not in ("/pr", "/分组"):
            try:
                result = await self.bridge.run_command(conv_key, text.strip())
            except Exception:  # noqa: BLE001 - unknown command must fall through, never crash
                result = {}
            if result.get("ok") and result.get("handled"):
                return
        if lowered == "/pr" or lowered.startswith("/pr "):
            preset = text[3:].strip()
            try:
                result = await self.bridge.permission(conv_key, preset or None)
            except BridgeError as error:
                await self.send_text(conv_key, "权限查询失败：" + str(error))
                return
            names = result.get("names") or []
            if preset:
                if result.get("ok"):
                    await self.send_text(conv_key, "已切换权限：" + preset + "（以 DSH 的提示为准）")
                else:
                    await self.send_text(conv_key, "切换失败：" + str(result.get("error")) + "；可用：" + ", ".join(names))
                return
            if not names:
                await self.send_text(conv_key, str(result.get("note") or result.get("error") or "权限预设不可用"))
                return
            current = str(result.get("current") or "")
            lines = ["当前权限：" + (current or "未知（会话未加载）")]
            lines.append("")
            lines.append("可选预设（实时，来自 DSH）：")
            for name in names:
                lines.append("- " + name + ("（默认）" if name == result.get("current") else ""))
            lines.append("")
            lines.append("切换：/pr <名字>（转发官方 /permission，不扩大权限）")
            await self.send_text(conv_key, chr(10).join(lines))
            return
        if await self.handle_extra_command(conv_key, text, lowered, is_owner=is_owner):
            return

        images, skipped = await self._collect_images(message.attachments)
        if skipped and not images:
            text = (text + "\n（对方发来图片，但我这边解不开：只支持 png/jpg/webp/gif，可能是 HEIF 或下载失败）").strip()
        if not text and not images:
            await self.send_text(conv_key, "在的，@我并说出你的问题就行。")
            return

        self.chime[conv_key] = {"count": 0.0, "last": time.time()}
        quote = self._quote_of(message)
        if quote is not None:
            self._bump("quotes")
            quoted_images = await self._quote_images(quote)
            if quoted_images:
                images = list(images) + quoted_images
        await self._queue_message(
            conv_key,
            text,
            self._owner_label(conv_key, member_openid) if is_owner else self._display_name(conv_key, member_openid),
            is_owner,
            images,
            chat=chat,
            quote=quote,
        )

    async def on_group_at_message_create(self, message: GroupMessage) -> None:
        try:
            await self._handle_group_at(message)
        except Exception as error:  # noqa: BLE001 - one bad message must not kill dispatch
            log.exception("group @ handler failed: %s", error)

    async def on_group_message_create(self, message: GroupMessage) -> None:
        """Full mode: @ commands work, plain chatter goes through the judge."""
        try:
            if (
                not self.config.group_full_mode
                or not self.config.groups_enabled
                or not self.rt_bool("group_enabled", True)
                or not self.rt_bool("enabled", True)
            ):
                return
            group_openid = message.group_openid or ""
            if not group_openid:
                return
            conv_key = f"group:{group_openid}"
            self._bump("group_msgs")
            member_openid = ""
            if message.author is not None:
                member_openid = message.author.member_openid or message.author.user_openid or ""
            text = clean_content(message.content)
            if message.id and message.id in self._seen_ids:
                return
            self._remember_id(message.id)
            self._pool_incoming(message, "group", group_openid, conv_key, short_id(member_openid))
            if member_openid:
                self._remember_member(conv_key, member_openid, _author_nick(message))
            log.info(
                "group message from %s: %r (keys=%s, mentions=%d)",
                short_id(member_openid),
                text[:80],
                ",".join(sorted((message.raw or {}).keys()))[:160],
                len(getattr(message, "mentions", None) or []),
            )
            mentioned = await self._mentions_bot(message)
            named = self.addresses_bot(text)
            commanded = text.startswith("/")
            at_only = self.rt_bool("group_at_only", False)
            if at_only is True and not mentioned:
                # at-only：别名/关键词、以及斜杠命令都不算被叫到，只有真 @ 才放行
                log.info("group chat ignored (at-only mode, named=%s cmd=%s)", named, commanded)
                return
            if mentioned or named or commanded:
                self._addressed_at[conv_key] = time.time()
                stale = self.chatter.pop(conv_key, None)
                if stale is not None and stale.timer is not None:
                    stale.timer.cancel()
                log.info("treat as addressed (mention=%s name=%s cmd=%s)", mentioned, named, commanded)
                await self._handle_group_at(message, chat=False)
                return
            if self.rt_str("group_mode", "A").strip().upper() == "B":
                await self._plan_b(conv_key, message, member_openid)
                return

            images, _skipped = await self._collect_images(message.attachments) if message.attachments else ([], 0)
            if images:
                self.recent_images[conv_key] = (images[-2:], time.time())
            if text:
                await self._buffer_chatter(conv_key, self._display_name(conv_key, member_openid), text)
                await self._maybe_judge(conv_key)
        except Exception as error:  # noqa: BLE001
            self._bump("errors")
            log.exception("group handler failed: %s", error)

    async def on_c2c_message_create(self, message: C2CMessage) -> None:
        try:
            await self._handle_c2c(message)
        except Exception as error:  # noqa: BLE001
            log.exception("c2c handler failed: %s", error)

    async def _handle_c2c(self, message: C2CMessage) -> None:
        # QQ 网关会在 ack 慢或重连时重投同一个事件；私聊必须先去重，否则一轮对话会被跑两次、回两条
        if message.id and message.id in self._seen_ids:
            log.info("duplicate c2c event ignored: %s", message.id)
            return
        self._remember_id(message.id)
        log.info(
            "c2c from %s: %r",
            short_id(((message.author.user_openid if message.author else "") or "")),
            clean_content(message.content)[:120],
        )
        if not self.rt_bool("enabled", True) or not self.rt_bool("c2c_enabled", True):
            return
        self._bump("c2c_msgs")
        user_openid = message.author.user_openid if message.author is not None else ""
        if not user_openid:
            return
        conv_key = f"c2c:{user_openid}"
        self._register(conv_key, "c2c", user_openid, message.id)

        if not self.owner_openid:
            self.owner_openid = user_openid
            self.state.owner_openid = user_openid
            self.state.save()
            log.info("owner claimed by first private message: %s", short_id(user_openid))
        is_owner = user_openid == self.owner_openid

        text = clean_content(message.content)
        self._pool_incoming(message, "c2c", user_openid, conv_key, f"用户{short_id(user_openid)}")
        lowered = text.lower()
        decision, approval_id = parse_decision(text)
        if decision is not None:
            if not is_owner:
                await self.send_text(conv_key, "只有主人可以审批。")
                return
            await self._resolve_approval(conv_key, decision, approval_id)
            return
        if lowered in RESET_COMMANDS:
            try:
                await self.bridge.reset(conv_key)
            except BridgeError as error:
                await self.send_text(conv_key, f"重置失败：{error}")
                return
            await self.send_text(conv_key, "已开新会话，上下文清空。")
            return
        if lowered in HELP_COMMANDS:
            await self.send_text(conv_key, self.help_text())
            return
        if lowered in ("/分组", "/workspace", "/ws"):
            try:
                result = await self.bridge.rebind(conv_key)
            except BridgeError as error:
                await self.send_text(conv_key, "创建分组失败：" + str(error))
                return
            if result.get("ok") and result.get("moved"):
                sandbox = result.get("sandbox")
                granted = ""
                if isinstance(sandbox, dict) and str(sandbox.get("granted") or "") == "failed":
                    granted = chr(10) + "⚠ 沙箱预授权失败：" + str(sandbox.get("reason") or "未知原因")
                await self.send_text(conv_key, "已迁移到工作区（上下文保留）：" + str(result.get("cwd")) + granted)
            elif result.get("ok"):
                reason = str(result.get("fallbackReason") or "")
                await self.send_text(conv_key, "已切到独立工作区：" + str(result.get("cwd")) + chr(10) + "方式：新建会话（上下文不继承）" + (("，原因：" + reason) if reason else ""))
            else:
                await self.send_text(conv_key, "创建分组失败：" + str(result.get("error")))
            return
        if lowered in ("/指令", "/commands"):
            try:
                result = await self.bridge.commands(conv_key)
            except BridgeError as error:
                await self.send_text(conv_key, "查询指令失败：" + str(error))
                return
            if not result.get("ok"):
                await self.send_text(conv_key, str(result.get("error") or "不可用"))
                return
            items = result.get("commands") or []
            lines = ["DSH 指令（实时，" + str(len(items)) + " 条）："]
            for item in items[:40]:
                desc = str(item.get("description") or "")
                lines.append("- /" + str(item.get("name")) + ((" — " + desc) if desc else ""))
            if len(items) > 40:
                lines.append("… 还有 " + str(len(items) - 40) + " 条")
            lines.append("")
            lines.append("直接用 /<名字> 就能执行（转给 DSH 官方命令通道）")
            await self.send_text(conv_key, chr(10).join(lines))
            return
        if lowered.startswith("/") and lowered not in ("/pr", "/分组"):
            try:
                result = await self.bridge.run_command(conv_key, text.strip())
            except Exception:  # noqa: BLE001 - unknown command must fall through, never crash
                result = {}
            if result.get("ok") and result.get("handled"):
                return
        if lowered == "/pr" or lowered.startswith("/pr "):
            preset = text[3:].strip()
            try:
                result = await self.bridge.permission(conv_key, preset or None)
            except BridgeError as error:
                await self.send_text(conv_key, "权限查询失败：" + str(error))
                return
            names = result.get("names") or []
            if preset:
                if result.get("ok"):
                    await self.send_text(conv_key, "已切换权限：" + preset + "（以 DSH 的提示为准）")
                else:
                    await self.send_text(conv_key, "切换失败：" + str(result.get("error")) + "；可用：" + ", ".join(names))
                return
            if not names:
                await self.send_text(conv_key, str(result.get("note") or result.get("error") or "权限预设不可用"))
                return
            current = str(result.get("current") or "")
            lines = ["当前权限：" + (current or "未知（会话未加载）")]
            lines.append("")
            lines.append("可选预设（实时，来自 DSH）：")
            for name in names:
                lines.append("- " + name + ("（默认）" if name == result.get("current") else ""))
            lines.append("")
            lines.append("切换：/pr <名字>（转发官方 /permission，不扩大权限）")
            await self.send_text(conv_key, chr(10).join(lines))
            return
        if await self.handle_extra_command(conv_key, text, lowered, is_owner=is_owner):
            return

        images, skipped = await self._collect_images(message.attachments)
        if skipped and not images:
            text = (text + "\n（对方发来图片，但我这边解不开：只支持 png/jpg/webp/gif，可能是 HEIF 或下载失败）").strip()
        if not text and not images:
            await self.send_text(conv_key, "说点什么，我转给 DSH。")
            return

        quote = self._quote_of(message)
        if quote is not None:
            self._bump("quotes")
            quoted_images = await self._quote_images(quote)
            if quoted_images:
                images = list(images) + quoted_images
        await self._queue_message(
            conv_key,
            text,
            self._owner_label(conv_key, user_openid) if is_owner else f"用户{short_id(user_openid)}",
            is_owner,
            images,
            quote=quote,
        )

    async def on_interaction_create(self, interaction: Interaction) -> None:
        """Handle 允许 / 拒绝 button clicks (only the owner may decide)."""
        data = interaction.data or {}
        resolved = data.get("resolved") or {}
        button_data = resolved.get("button_data") or data.get("button_data") or ""
        clicker = (interaction.user_openid or interaction.group_member_openid or "").strip()
        owner = (self.owner_openid or "").strip()
        if owner and clicker and clicker.upper() != owner.upper():
            # 点的人不是主人：QQ 会把这个 code 显示成「无权限操作」
            log.warning(
                "approval click rejected: clicker=%s owner=%s",
                short_id(clicker),
                short_id(owner),
            )
            await self._interaction_result(interaction, 4)
            return
        # 提问按钮必须在审批解析之前拦掉：它的 data 不是「允许/拒绝 <id>」
        picked = str(button_data).strip().split()
        if len(picked) == 3 and picked[0] == "选择":
            question_id, raw_index = picked[1], picked[2]
            conv_for_answer = f"c2c:{clicker}" if clicker else self._owner_conv()
            await self._interaction_result(interaction, 0)
            try:
                self._bump("questions_answered")
                await self.bridge.answer_question(question_id, int(raw_index))
                log.info("question %s answered with option %s", short_id(question_id), raw_index)
            except Exception as error:  # noqa: BLE001 - the question may have expired
                log.warning("answer delivery failed: %s", error)
                await self.send_text(conv_for_answer, "这个提问已经失效了（或插件还没重启加载 /answer）。")
            return
        # 踢人二次确认：data 形如「踢人确认 <id> yes」/「踢人确认 <id> no」
        kick_hit = parse_kick_confirm(str(button_data))
        if kick_hit is not None:
            await self._resolve_kick_confirm(interaction, *kick_hit)
            return
        decision, approval_id = parse_decision(str(button_data))
        if decision is None:
            await self._interaction_result(interaction, 1)
            return
        if approval_id and approval_id in self._decided:
            log.info("approval %s already decided (%s); ignoring repeat click", short_id(approval_id), self._decided[approval_id])
            await self._interaction_result(interaction, 1)
            return
        conv_key = f"c2c:{clicker}" if clicker else self._owner_conv()
        # 先回执再干活：QQ 的交互回调有硬超时，超时后客户端会把按钮 data 当文本消息发出来
        # （表现就是群里多出一条「允许 <uuid>」）。
        await self._interaction_result(interaction, 0)
        self._spawn_approval(conv_key, decision, approval_id)

    async def _interaction_result(self, interaction: Interaction, code: int) -> None:
        try:
            await self.api.on_interaction_result(interaction_id=interaction.id, code=code)
        except Exception as error:  # noqa: BLE001 - best effort acknowledgement
            log.warning("interaction result failed: %s", error)

    async def on_group_add_robot(self, event: Any) -> None:
        group_openid = getattr(event, "group_openid", "") or ""
        log.info("bot added to group %s", short_id(group_openid))
        self.group_state.pop(group_openid, None)

    async def on_group_del_robot(self, event: Any) -> None:
        group_openid = getattr(event, "group_openid", "") or ""
        log.info("bot removed from group %s", short_id(group_openid))
        self.group_state.pop(group_openid, None)
        self.targets.pop(f"group:{group_openid}", None)

    async def on_group_msg_receive(self, event: Any) -> None:
        group_openid = getattr(event, "group_openid", "") or ""
        log.info("group %s enabled proactive messages", short_id(group_openid))
        self.group_state.pop(group_openid, None)

    async def on_group_msg_reject(self, event: Any) -> None:
        group_openid = getattr(event, "group_openid", "") or ""
        log.warning("group %s disabled proactive messages", short_id(group_openid))
        self.group_state.pop(group_openid, None)

    def help_text(self) -> str:
        return "\n".join(
            [
                f"我是 {self.config.botname}：DeepSeek Harness 的 QQ 入口。",
                "· /状态 看授权、/窗口 列窗口、/截图 <关键字> 截图发你",
                "· 连续发几条会合并成一条再处理；发图我能看图",
                "· 群里 @ 我才干活，其它时候像群友一样听着、偶尔插一句",
                "· /新会话（/重置）清空上下文；群里 /绑定 把自己绑成群主",
                "· /会话 看绑定，/切会话 <id> 换会话，/切回 回到原会话",
                "· /花费 看本会话 token 用量（/花费 全部 看最近所有会话）",
                "· /菜单 弹出按钮面板，常用指令一点就走",
                "· /消息池 看最近 10 分钟收发（/池），/撤回 [n|#序号] 撤我发的或指定那条",
                "· 需要授权时审批发到主人单聊：点按钮或回「允许」/「拒绝」",
            ]
        )


# --------------------------------------------------------------------------- #
# process control: run / supervise (auto-restart + panel) / stop
# --------------------------------------------------------------------------- #
STATE_DIR = Path(os.environ.get("DSH_QQBOT_STATE_DIR") or (ROOT / "state"))
LOG_DIR = ROOT / "logs"
MEMBERS_FILE = STATE_DIR / "members.json"
STREAMS_FILE = STATE_DIR / "streams.json"
METRICS_FILE = STATE_DIR / "metrics.json"
METRICS_DIR = STATE_DIR / "metrics"
GROUPS_FILE = STATE_DIR / "groups.json"
STOP_FLAG = STATE_DIR / "stop.flag"
SUPERVISOR_PID = STATE_DIR / "supervisor.pid"
CHILD_PID = STATE_DIR / "child.pid"
CURSOR_FILE = ROOT / "state" / "cursor.txt"
RESTART_DELAYS = (2, 5, 15, 30)


def _write_pid(path: Path, pid: int) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid), encoding="utf-8")


def _read_pid(path: Path) -> Optional[int]:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _alive(pid: int) -> bool:
    """Whether the process still exists (Windows: tasklist, else signal 0)."""
    try:
        if os.name == "nt":
            result = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True)
            return str(pid) in (result.stdout or "")
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _kill_tree(pid: int) -> None:
    """Terminate one process and its children (Windows taskkill, else SIGKILL)."""
    if pid <= 0:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
        else:
            os.kill(pid, signal.SIGKILL)
    except OSError as error:
        log.warning("could not stop pid %s: %s", pid, error)



def reason_text(value: Any) -> str:
    """Turn-end reason as a readable string (the host sends an object)."""
    if isinstance(value, str):
        # the host stringifies its turn-end object; treat that as "unknown"
        return '' if value.strip() in ('[object Object]', 'undefined', 'null') else value
    if isinstance(value, dict):
        for key in ('kind', 'type', 'reason', 'message'):
            if isinstance(value.get(key), str):
                return value[key]
        return ''
    return ''


def _attachment_url(attachment):
    """Best-effort URL out of one quoted-media attachment."""
    if isinstance(attachment, str):
        return attachment.strip() or None
    if isinstance(attachment, dict):
        for key in ("url", "file_url", "remote_url", "src", "thumb_url"):
            value = attachment.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _sent_idx(result):
    """msg_idx of a message we just sent: QQ returns it as ext_info.ref_idx."""
    if isinstance(result, dict):
        ext = result.get("ext_info")
        if isinstance(ext, dict) and isinstance(ext.get("ref_idx"), str):
            return ext["ref_idx"]
        for key in ("msg_idx", "idx", "ref_idx"):
            if isinstance(result.get(key), str):
                return result[key]
        return ""
    for attr in ("msg_idx", "idx"):
        value = getattr(result, attr, "")
        if isinstance(value, str):
            return value
    return ""


def _scene_ext(scene):
    """Flatten message_scene.ext into a dict of key -> value.

    Real payloads carry a list like ["ref_msg_idx=REFIDX_...", "msg_idx=REFIDX_...",
    "auth_token=..."], so only explicit keys are trusted; anything else is noise.
    """
    if not isinstance(scene, dict):
        return {}
    flat = {}
    ext = scene.get("ext")
    if isinstance(ext, dict):
        flat.update({k: v for k, v in ext.items() if isinstance(v, str)})
    elif isinstance(ext, list):
        for entry in ext:
            if isinstance(entry, str) and "=" in entry:
                key, value = entry.split("=", 1)
                flat[key.strip()] = value.strip()
            elif isinstance(entry, dict):
                for key, value in entry.items():
                    if isinstance(value, str):
                        flat[str(key)] = value
    for key in ("ref_msg_idx", "msg_idx"):
        value = scene.get(key)
        if isinstance(value, str) and value.strip():
            flat.setdefault(key, value.strip())
    return flat


AT_EVERYONE_TOKEN = "<qqbot-at-everyone />"
OPENID_RE = re.compile(r"@?(?<!群友)(?<![0-9A-Za-z])([0-9A-Fa-f]{6,32})(?![0-9A-Za-z])")
_AT_ALIAS_RE = re.compile(r"@群友([0-9A-Fa-f]{4,8})")


def _decode_line(raw: bytes) -> str:
    """Child stdout may be UTF-8 or the legacy GBK console encoding."""
    for encoding in ("utf-8", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _heartbeat() -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        (STATE_DIR / "alive.txt").write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass


def run_bot() -> int:
    """One bot process, no supervision."""
    from dataclasses import replace as dataclass_replace

    from runtime_config import RuntimeConfig

    configure_logging(log_file=str(LOG_DIR / "viseron_qqbotpy.log"))
    config = load_config()
    runtime = RuntimeConfig()
    overrides = {}
    if runtime.get("appid"):
        overrides["appid"] = str(runtime.get("appid"))
    if runtime.get("appsecret"):
        overrides["secret"] = str(runtime.get("appsecret"))
    if runtime.get("bridge_url"):
        overrides["bridge_url"] = str(runtime.get("bridge_url"))
    if runtime.get("bridge_token"):
        overrides["bridge_token"] = str(runtime.get("bridge_token"))
    if overrides:
        config = dataclass_replace(config, **overrides)
    bot = DSHBot(intents=Intents.default(), config=config)
    bot.rt = runtime
    log.info("[%s] starting appid=%s bridge=%s", config.botname, config.appid, config.bridge_url)
    bot.run(appid=config.appid, secret=config.secret)
    return 0


def supervise() -> int:
    """Own the bot process and the settings page (面板 + 日志 + 进程管理)."""
    from panel import start_panel
    from runtime_config import RuntimeConfig
    from viseron_qqbotpy import load_env

    # 守护进程写自己的日志文件：两个进程同写一个文件会让轮转报 WinError 32，
    # 日志永远切不开（旧日志会一直涨并淹没真实错误）。
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        configure_logging(log_file=str(LOG_DIR / "supervisor.log"))
    except Exception as error:  # noqa: BLE001 - logging must never block startup
        print(f"[supervisor] logging setup failed: {error}", flush=True)

    load_env(ROOT / ".env")
    runtime = RuntimeConfig()
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    # Single instance only: two supervisors share config.json and would fight
    # over desired_running (visible as a bot that starts and stops by itself).
    existing = _read_pid(SUPERVISOR_PID)
    if existing and existing != os.getpid() and _alive(existing):
        print(f"[supervisor] already running as pid={existing}; exiting", flush=True)
        return 0

    STOP_FLAG.unlink(missing_ok=True)
    _write_pid(SUPERVISOR_PID, os.getpid())

    state: Dict[str, Any] = {"child": None, "started_at": 0.0, "attempt": 0, "next_at": 0.0, "note": "starting", "log": []}
    lock = threading.Lock()
    log_path = STATE_DIR / "bot-output.log"
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if os.name == "nt" else 0

    def pump(stream: Any) -> None:
        """Mirror the child's console output into a ring buffer and a file."""
        try:
            handle = open(log_path, "ab", buffering=0)
        except OSError:
            handle = None
        try:
            for raw in iter(stream.readline, b""):
                line = _decode_line(raw).rstrip("\r\n")
                line = re.sub(r"\x1b\[[0-9;]*m", "", line)
                if line.strip() == "":
                    continue
                with lock:
                    ring = state["log"]
                    ring.append(line)
                    if len(ring) > 600:
                        del ring[: len(ring) - 600]
                if handle is not None:
                    try:
                        handle.write((line + "\n").encode("utf-8", "replace"))
                    except OSError:
                        pass
        finally:
            if handle is not None:
                handle.close()

    def online() -> bool:
        try:
            return (time.time() - (STATE_DIR / "alive.txt").stat().st_mtime) < 45
        except OSError:
            return False

    def bridge_state() -> str:
        import json as _json
        import urllib.request
        url = str(runtime.get("bridge_url") or "")
        token = str(runtime.get("bridge_token") or os.getenv("BRIDGE_TOKEN", ""))
        if not url:
            return "unset"
        try:
            request = urllib.request.Request(url.rstrip("/") + "/health", headers={"x-bridge-token": token})
            with urllib.request.urlopen(request, timeout=2) as response:
                payload = _json.loads(response.read().decode("utf-8"))
            return str(payload.get("service") or "unknown")
        except Exception:
            return "down"

    def spawn() -> None:
        with lock:
            child = state["child"]
            if child is not None and child.poll() is None:
                return
            child_env = dict(os.environ)
            child_env["PYTHONIOENCODING"] = "utf-8"
            child_env["PYTHONUTF8"] = "1"
            process = subprocess.Popen(
                [sys.executable, "-u", str(Path(__file__).resolve()), "--run"],
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=no_window,
                env=child_env,
            )
            state["child"] = process
            state["started_at"] = time.time()
            state["note"] = f"bot pid={process.pid} up"
            _write_pid(CHILD_PID, process.pid)
            threading.Thread(target=pump, args=(process.stdout,), daemon=True).start()
            print(f"[supervisor] bot pid={process.pid} up", flush=True)

    def kill_child() -> None:
        with lock:
            child = state["child"]
            if child is None:
                return
            if child.poll() is None:
                _kill_tree(child.pid)
            state["child"] = None
            CHILD_PID.unlink(missing_ok=True)
            print("[supervisor] bot stopped", flush=True)

    async def perform(action: str) -> str:
        if action == "start":
            runtime.update({"desired_running": True})
            STOP_FLAG.unlink(missing_ok=True)
            state["attempt"] = 0
            state["next_at"] = 0.0
            spawn()
            state["note"] = "已启动"
            return "已启动"
        if action == "stop":
            runtime.update({"desired_running": False})
            kill_child()
            state["note"] = "已停止（不会自动拉起）"
            return "已停止（不会自动拉起）"
        runtime.update({"desired_running": True})
        STOP_FLAG.unlink(missing_ok=True)
        kill_child()
        state["attempt"] = 0
        state["next_at"] = 0.0
        time.sleep(0.6)
        spawn()
        state["note"] = "已重启（凭据等改动已生效）"
        return "已重启（凭据等改动已生效）"

    def status() -> Dict[str, Any]:
        child = state["child"]
        running = child is not None and child.poll() is None
        note = state.get("note", "")
        if runtime.get_bool("desired_running") is False:
            note = "已停止（不会自动拉起）"
        return {
            "running": running,
            "pid": child.pid if running else 0,
            "online": running and online(),
            "desired": runtime.get_bool("desired_running"),
            "supervisor": os.getpid(),
            "uptime_s": int(time.time() - state["started_at"]) if running else 0,
            "note": note,
        }

    def logs(limit: int = 300) -> List[str]:
        with lock:
            return list(state["log"])[-max(1, min(limit, 600)):]

    control = type("Control", (), {
        "status": staticmethod(status),
        "perform": staticmethod(perform),
        "bridge_state": staticmethod(bridge_state),
        "logs": staticmethod(logs),
    })

    host = str(runtime.get("panel_host") or "127.0.0.1")
    port = runtime.get_int("panel_port")
    token = str(runtime.get("bridge_token") or os.getenv("PANEL_TOKEN") or os.getenv("BRIDGE_TOKEN", ""))
    start_panel(control, runtime, host, port, token)

    print(f"[supervisor] pid={os.getpid()} supervising (panel http://{host}:{port}/)", flush=True)
    try:
        while True:
            desired = runtime.get_bool("desired_running")
            child = state["child"]
            running = child is not None and child.poll() is None

            if running and not desired:
                kill_child()
            elif desired and not running:
                if child is not None:
                    code = child.returncode
                    print(f"[supervisor] bot exited code={code}", flush=True)
                    state["child"] = None
                    CHILD_PID.unlink(missing_ok=True)
                    uptime = time.time() - state["started_at"]
                    state["attempt"] = 0 if uptime > 300 else state["attempt"] + 1
                    delay = RESTART_DELAYS[min(state["attempt"] - 1, len(RESTART_DELAYS) - 1)] if state["attempt"] else 2
                    state["next_at"] = time.time() + delay
                    state["note"] = f"崩溃退出（code={code}），{delay}s 后重启"
                    print(f"[supervisor] restarting in {delay}s", flush=True)
                if time.time() >= state["next_at"]:
                    spawn()

            time.sleep(1.0)
    except KeyboardInterrupt:
        print("[supervisor] interrupted", flush=True)
        kill_child()
        return 0
    finally:
        STOP_FLAG.unlink(missing_ok=True)
        for path in (CHILD_PID, SUPERVISOR_PID):
            path.unlink(missing_ok=True)


def request_stop() -> int:
    """Stop everything: park the bot and end the supervisor process."""
    from runtime_config import RuntimeConfig

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    RuntimeConfig().update({"desired_running": False})
    STOP_FLAG.write_text("stop", encoding="utf-8")
    supervisor = _read_pid(SUPERVISOR_PID)
    child = _read_pid(CHILD_PID)
    print(f"[stop] flag written (supervisor={supervisor}, bot={child})", flush=True)
    if child:
        _kill_tree(child)
    if supervisor:
        for _ in range(60):
            time.sleep(0.1)
            if not _alive(supervisor):
                break
        else:
            _kill_tree(supervisor)
    for path in (CHILD_PID, SUPERVISOR_PID):
        path.unlink(missing_ok=True)
    print("[stop] stopped; panel and auto-restart are off until the next start", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="DeepSeek Harness QQ bot")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--run", action="store_true", help="run the bot only (used by --supervise)")
    group.add_argument("--supervise", action="store_true", help="run with auto-restart and the settings panel")
    group.add_argument("--stop", action="store_true", help="stop a supervised bot and keep it stopped")
    args = parser.parse_args()
    if args.stop:
        return request_stop()
    if args.supervise:
        return supervise()
    return run_bot()


if __name__ == "__main__":
    sys.exit(main())