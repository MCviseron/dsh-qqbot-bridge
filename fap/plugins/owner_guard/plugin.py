"""owner_guard：主人身份插件（框架本身不认识「主人」）。

职责：
1. 维护 owners 列表（config 指定，或首次认领），落盘到自己的状态目录；
2. 向框架的 PermissionRegistry 声明 "owner" 角色；
3. 提供 /认领、/主人、/移交 三条命令。

其它插件只需给命令加 requires="owner"，不必实现任何身份逻辑。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from framework.plugin import Plugin, PluginContext
from framework.settings import SettingSpec

DEFAULTS = {
    "owners": [],             # 显式指定的主人 openid
    "claim_on_first": True,   # 还没有主人时允许认领
}


class OwnerGuardPlugin(Plugin):
    id = "owner_guard"
    name = "主人 / 权限"
    version = "1.0.0"
    description = "认领/移交主人，并向框架声明 owner 角色"

    def __init__(self) -> None:
        super().__init__()
        self._store: Any = None
        self._owners: List[str] = []

    # -- 配置与数据 ---------------------------------------------------------
    def cfg(self, key: str, default: Any = None) -> Any:
        section = dict(DEFAULTS)
        if self.ctx is not None:
            section.update(self.ctx.config())
        return section.get(key, default)

    def load(self) -> None:
        configured = self.cfg("owners") or []
        if isinstance(configured, str):
            configured = [item.strip() for item in configured.split(",") if item.strip()]
        stored = self._store.get("owners", []) or []
        merged: List[str] = []
        for openid in list(configured) + list(stored):
            if openid and openid not in merged:
                merged.append(str(openid))
        self._owners = merged

    def save(self) -> None:
        self._store.set("owners", self._owners)
        self._store.set("updated_at", time.time())

    def is_owner(self, openid: str) -> bool:
        return bool(openid) and openid in self._owners

    def claim(self, openid: str) -> bool:
        if not openid or self._owners:
            return False
        self._owners = [openid]
        self.save()
        return True

    # -- 生命周期 -----------------------------------------------------------
    async def setup(self, ctx: PluginContext) -> None:
        self._store = ctx.store("owner")
        self.load()
        ctx.permissions.register(self._check_role, plugin=self.id, name="owner")
        ctx.declare_settings(
            [
                SettingSpec("owners", "主人 openid", "list", [], "留空则允许 /认领"),
                SettingSpec("claim_on_first", "允许认领", "bool", True, "还没有主人时，谁先发 /认领 谁就是主人"),
            ]
        )

        @ctx.command("认领", summary="认领主人身份（还没有主人时）", order=6)
        async def _claim(context) -> None:
            if self._owners:
                await context.say("已经有主人了（" + self.describe() + "）。要交接用 /移交 <短号>。")
                return
            if not self.cfg("claim_on_first", True):
                context.fail("认领已关闭：请在 config.json 的 plugins.owner_guard.owners 指主人 openid。")
            self.claim(context.sender.openid)
            ctx.log.info("owner claimed by %s", context.sender.short)
            await context.say("认领成功，" + context.sender.display + " 现在是主人。")

        @ctx.command("主人", aliases=("owner",), summary="查看当前主人", order=7)
        async def _owner(context) -> None:
            if not self._owners:
                await context.say("还没有主人：发 /认领 即可（谁先认领算谁）。")
                return
            await context.say("当前主人：" + self.describe())

        @ctx.command("移交", summary="把主人身份交给别人", usage="<短号|openid>", requires="owner", order=8)
        async def _handover(context) -> None:
            if not context.args:
                context.fail("用法：/移交 <短号或 openid>")
            resolved = self._resolve(context, context.args[0].strip())
            if not resolved:
                context.fail("找不到这个人：让他先在群里发过言，或用完整 openid。")
            self._owners = [resolved]
            self.save()
            await context.say("已把主人身份移交给 …" + resolved[-6:])

        ctx.log.info("owner_guard ready（%s）", self.describe())

    # -- 判定 ---------------------------------------------------------------
    def _check_role(self, message: Any, role: str) -> bool:
        if role != "owner":
            return False
        return self.is_owner(getattr(getattr(message, "sender", None), "openid", ""))

    def _resolve(self, context: Any, target: str) -> Optional[str]:
        if len(target) >= 16:
            return target
        index = (getattr(context.app, "members", {}) or {}).get(context.conv_key, {})
        for tail, openid in index.items():
            if str(tail).upper() == target.upper():
                return str(openid)
        return None

    def describe(self) -> str:
        return "、".join("…" + openid[-6:] for openid in self._owners) or "（无）"
