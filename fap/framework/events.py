"""事件总线：插件之间只通过事件通信，互不 import。"""

from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List

from framework.logging import get

log = get("events")

Handler = Callable[..., Any]


@dataclass
class Subscription:
    event: str
    handler: Handler
    plugin: str = ""
    priority: int = 0
    once: bool = False


class EventBus:
    """极简异步事件总线。

    支持通配 "*"，按 priority 升序调用；单个处理器异常只记日志，不影响其它订阅者。
    """

    def __init__(self, history: int = 200) -> None:
        self._subs: List[Subscription] = []
        self._history_limit = max(0, int(history))
        self._history: List[Dict[str, Any]] = []
        self._seq = 0

    def on(
        self,
        event: str,
        handler: Handler,
        *,
        plugin: str = "",
        priority: int = 0,
        once: bool = False,
    ) -> Subscription:
        subscription = Subscription(event=event, handler=handler, plugin=plugin, priority=priority, once=once)
        self._subs.append(subscription)
        self._subs.sort(key=lambda item: item.priority)
        return subscription

    def off(self, subscription: Subscription) -> None:
        if subscription in self._subs:
            self._subs.remove(subscription)

    def off_plugin(self, plugin: str) -> int:
        before = len(self._subs)
        self._subs = [item for item in self._subs if item.plugin != plugin]
        return before - len(self._subs)

    def _record(self, event: str, payload: Dict[str, Any]) -> None:
        """只留“能展示”的摘要：不存 Message 之类的对象，GUI 才不会炸。"""
        if self._history_limit <= 0:
            return
        self._seq += 1
        summary: Dict[str, Any] = {"seq": self._seq, "at": time.time(), "event": event}
        for key, value in payload.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                summary[key] = value
            elif key == "message":
                summary["convKey"] = getattr(value, "conv_key", "")
                summary["text"] = str(getattr(value, "text", ""))[:80]
                sender = getattr(value, "sender", None)
                summary["sender"] = getattr(sender, "display", "") if sender is not None else ""
            elif key == "target":
                summary["convKey"] = getattr(value, "conv_key", "")
        self._history.append(summary)
        if len(self._history) > self._history_limit:
            del self._history[: len(self._history) - self._history_limit]

    def history(self, since: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        rows = [row for row in self._history if int(row.get("seq", 0)) > int(since)]
        return rows[-limit:]

    def handlers(self, event: str) -> List[Subscription]:
        return [item for item in self._subs if item.event in (event, "*")]

    async def emit(self, event: str, **payload: Any) -> List[Any]:
        self._record(event, payload)
        results: List[Any] = []
        for subscription in list(self.handlers(event)):
            try:
                outcome = subscription.handler(event=event, **payload)
                if inspect.isawaitable(outcome):
                    outcome = await outcome
                results.append(outcome)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - 订阅者互相隔离
                log.exception("event %s handler failed (%s): %s", event, subscription.plugin or "-", error)
                results.append(error)
            finally:
                if subscription.once:
                    self.off(subscription)
        return results


async def gather_guard(awaitables: List[Awaitable[Any]]) -> None:
    """并发执行且吞掉单个异常（后台任务用）。"""
    if not awaitables:
        return
    for outcome in await asyncio.gather(*awaitables, return_exceptions=True):
        if isinstance(outcome, Exception):
            log.warning("background task failed: %s", outcome)
