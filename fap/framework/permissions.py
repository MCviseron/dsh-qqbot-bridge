"""权限（角色）注册表：框架只认「角色名」，谁给角色由插件决定。

框架本身不认识「主人」——那是业务。插件通过本注册表声明某人是否拥有某个角色
（owner / admin / vip…），命令用 requires="owner" 引用角色。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict, List

if TYPE_CHECKING:  # pragma: no cover
    from framework.types import Message

Checker = Callable[["Message", str], Any]


class PermissionRegistry:
    def __init__(self) -> None:
        self._checkers: List[Dict[str, Any]] = []

    def register(self, checker: Checker, *, plugin: str = "", name: str = "") -> None:
        self._checkers.append({"checker": checker, "plugin": plugin, "name": name or plugin})

    def unregister_plugin(self, plugin: str) -> int:
        before = len(self._checkers)
        self._checkers = [row for row in self._checkers if row["plugin"] != plugin]
        return before - len(self._checkers)

    def providers(self) -> List[str]:
        return [str(row["name"]) for row in self._checkers]

    def has(self, message: "Message", role: str) -> bool:
        """任一插件承认即通过；没有插件声明该角色时一律拒绝（默认安全）。"""
        if not role:
            return True
        sender = getattr(message, "sender", None)
        if sender is None:
            return False
        for row in list(self._checkers):
            try:
                if row["checker"](message, role) is True:
                    return True
            except Exception:  # noqa: BLE001 - 判定失败按无权限处理
                continue
        return False
