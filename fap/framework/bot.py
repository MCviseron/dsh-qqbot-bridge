"""QQ 客户端封装：只做三件事——连上、把 SDK 事件归一化成 Message、发消息。

SDK 只在真正启动时才 import，因此框架在没有安装 SDK 的环境里也能被导入和测试。
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional

from framework.logging import get
from framework.types import Message, Sender, Target

log = get("bot")

MENTION_RE = re.compile(r"<@!?([0-9A-Za-z_-]{8,})>")
QAT_USER_RE = re.compile(r"<qqbot-at-user[^>]*?\bid=\"([^\"]+)\"[^>]*>", re.IGNORECASE)
INLINE_TAG_RE = re.compile(r"<(?:faceType|img|qqbot-cmd-enter|qqbot-at-user|emoji)[^>]*>", re.IGNORECASE)


def clean_text(raw: Optional[str]) -> str:
    """把 QQ 的标签文本变成可读文本：@ 保留（占位），其它内联标签删掉。"""
    text = str(raw or "").strip()
    text = MENTION_RE.sub(lambda hit: "@群友" + hit.group(1)[-6:].upper(), text)
    text = QAT_USER_RE.sub(lambda hit: "@群友" + hit.group(1)[-6:].upper(), text)
    text = INLINE_TAG_RE.sub("", text)
    return " ".join(text.split()).strip()


class QQBot:
    """包一层 SDK 的 Client；框架其它部分不直接碰 SDK。"""

    def __init__(self, app: Any) -> None:
        self.app = app
        self._client: Any = None
        self._ready = asyncio.Event()

    # -- 生命周期 -----------------------------------------------------------
    def _build_client(self) -> Any:
        from viseron_qqbotpy import Client  # 延迟 import：离线环境也能导入框架

        app = self.app

        class _Client(Client):
            async def on_ready(client_self) -> None:  # noqa: N805 - SDK 约定
                self._ready.set()
                await app.on_bot_ready()

            async def on_group_message_create(client_self, message) -> None:  # noqa: N805
                await self._dispatch(message, kind="group")

            async def on_c2c_message_create(client_self, message) -> None:  # noqa: N805
                await self._dispatch(message, kind="c2c")

            async def on_interaction_create(client_self, interaction) -> None:  # noqa: N805
                await app.on_interaction(interaction)

        return _Client()

    def run(self) -> None:
        config = self.app.config
        self._client = self._build_client()
        self._client.run(appid=str(config.get("appid")), secret=str(config.get("appsecret")))
        return None

    def start_background(self) -> None:
        """把 SDK 的阻塞 run() 丢到后台线程（GUI 模式用）。"""
        import threading

        thread = threading.Thread(target=self.run, name="fap-bot", daemon=True)
        thread.start()

    # -- 入站 ---------------------------------------------------------------
    async def _dispatch(self, message: Any, *, kind: str) -> None:
        try:
            normalized = self._normalize(message, kind=kind)
        except Exception as error:  # noqa: BLE001 - 归一化失败不能打断网关
            log.exception("normalize failed (%s): %s", kind, error)
            return
        if normalized is None:
            return
        await self.app.on_message(normalized)

    def _normalize(self, message: Any, *, kind: str) -> Optional[Message]:
        message_id = str(getattr(message, "id", "") or "")
        if not message_id:
            return None
        author = getattr(message, "author", None)
        if kind == "group":
            openid = ""
            if author is not None:
                openid = getattr(author, "member_openid", "") or getattr(author, "user_openid", "") or ""
            conv_openid = str(getattr(message, "group_openid", "") or "")
            at_bot = bool(getattr(message, "mentions", None))
        else:
            openid = str(getattr(author, "user_openid", "") or "") if author is not None else ""
            conv_openid = openid
            at_bot = True
        if not conv_openid:
            return None
        nickname = ""
        for attr in ("username", "member_nickname", "nickname"):
            value = getattr(author, attr, None) if author is not None else None
            if isinstance(value, str) and value.strip():
                nickname = value.strip()
                break
        target = Target(kind=kind, openid=conv_openid, conv_key=kind + ":" + conv_openid)
        sender = Sender(openid=openid, nickname=nickname, is_owner=self.app.is_owner(openid))
        images = self._collect_images(message)
        return Message(
            id=message_id,
            kind=kind,
            conv_key=target.conv_key,
            sender=sender,
            text=clean_text(getattr(message, "content", "")),
            target=target,
            raw={"kind": kind},
            images=images,
            at_bot=at_bot,
        )

    @staticmethod
    def _collect_images(message: Any) -> List[str]:
        urls: List[str] = []
        for attachment in getattr(message, "attachments", None) or []:
            url = str(getattr(attachment, "url", "") or "")
            if url and str(getattr(attachment, "content_type", "") or "").startswith("image"):
                urls.append(url)
        return urls[:4]

    # -- 出站 ---------------------------------------------------------------
    async def send(self, target: Target, text: str, *, keyboard: Optional[Dict[str, Any]] = None) -> Any:
        if self._client is None:
            log.warning("bot not started; dropping outbound to %s", target.conv_key)
            return None
        api = getattr(self._client, "api", None)
        if api is None:
            return None
        chunks = self.split(text, int(self.app.config.get("max_chars", 1500)))
        results = []
        for index, chunk in enumerate(chunks):
            payload: Dict[str, Any] = {"msg_type": 0, "content": chunk, "msg_seq": index + 1}
            if keyboard is not None and index == len(chunks) - 1:
                payload["keyboard"] = keyboard
            try:
                if target.kind == "group":
                    results.append(await api.post_group_message(group_openid=target.openid, **payload))
                else:
                    results.append(await api.post_c2c_message(openid=target.openid, **payload))
            except Exception as error:  # noqa: BLE001 - 发送失败只记日志
                log.warning("send failed (%s): %s", target.conv_key, error)
        return results[-1] if results else None

    @staticmethod
    def split(text: str, limit: int = 1500) -> List[str]:
        body = str(text or "").strip()
        if not body:
            return []
        if limit <= 0 or len(body) <= limit:
            return [body]
        chunks: List[str] = []
        remaining = body
        while remaining:
            chunks.append(remaining[:limit])
            remaining = remaining[limit:]
        return chunks
