"""框架层的消息与目标抽象：与具体 SDK 解耦。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Sender:
    """发消息的人。openid 在群聊里是 member_openid，私聊里是 user_openid。"""

    openid: str
    nickname: str = ""

    @property
    def short(self) -> str:
        key = self.openid or ""
        return key[-6:].upper() if len(key) > 6 else key.upper()

    @property
    def display(self) -> str:
        return self.nickname or ("群友" + self.short)


@dataclass
class Target:
    """回复目标：一段会话（群或私聊）。"""

    kind: str            # group | c2c
    openid: str          # group_openid | user_openid
    conv_key: str        # group:<id> / c2c:<id>

    @staticmethod
    def from_key(conv_key: str) -> "Target":
        kind, _, openid = conv_key.partition(":")
        return Target(kind=kind or "c2c", openid=openid, conv_key=conv_key)


@dataclass
class Message:
    """一条入站消息（已归一化，插件不直接碰 SDK 对象）。"""

    id: str
    kind: str                       # group | c2c
    conv_key: str
    sender: Sender
    text: str
    target: Target
    raw: Dict[str, Any] = field(default_factory=dict)
    images: List[str] = field(default_factory=list)
    at_bot: bool = False
    reply_to: Optional[str] = None

    @property
    def is_group(self) -> bool:
        return self.kind == "group"


@dataclass
class Outgoing:
    """一条出站内容。"""

    text: str
    images: List[str] = field(default_factory=list)
    keyboard: Optional[Dict[str, Any]] = None
    markdown: Optional[bool] = None
