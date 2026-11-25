"""设置声明：框架与插件各报自己的可编辑项，GUI 据此自动画表单。

一个 SettingSpec 就是一行配置：键名、标题、类型、说明、属于框架还是某个插件。
GUI 只认这些描述，不为每个插件写死界面；保存时写回 config.json 并即时生效
（Config 走 mtime 热加载，但 update() 会直接刷新内存）。

    ctx.settings([
        SettingSpec("feed_cooldown_s", "喂食冷却（秒）", "int", 30, "同一只宠物两次喂食的最小间隔"),
    ])
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

KINDS = ("text", "secret", "int", "float", "bool", "list", "choice")


@dataclass
class SettingSpec:
    key: str                      # 配置键（插件内则是 plugins.<id>.<key>）
    label: str
    kind: str = "text"            # text | secret | int | float | bool | list | choice
    default: Any = ""
    help: str = ""
    choices: List[str] = field(default_factory=list)
    owner: str = ""               # "" = 框架；否则为插件 id

    def coerce(self, raw: Any) -> Any:
        """把界面上的字符串转成配置里该有的类型。"""
        if self.kind == "bool":
            if isinstance(raw, bool):
                return raw
            return str(raw).strip().lower() in {"1", "true", "yes", "on", "启用", "开"}
        if self.kind == "int":
            try:
                return int(float(str(raw).strip()))
            except (TypeError, ValueError):
                return int(self.default or 0)
        if self.kind == "float":
            try:
                return float(str(raw).strip())
            except (TypeError, ValueError):
                return float(self.default or 0.0)
        if self.kind == "list":
            if isinstance(raw, list):
                return raw
            return [item.strip() for item in str(raw).replace("，", ",").split(",") if item.strip()]
        return str(raw)


class SettingsRegistry:
    def __init__(self) -> None:
        self._specs: Dict[str, List[SettingSpec]] = {"": []}

    def register(self, specs: List[SettingSpec], *, owner: str = "") -> None:
        for spec in specs:
            spec.owner = owner
        bucket = self._specs.setdefault(owner, [])
        existing = {spec.key for spec in bucket}
        for spec in specs:
            if spec.key in existing:
                bucket[[index for index, row in enumerate(bucket) if row.key == spec.key][0]] = spec
            else:
                bucket.append(spec)

    def unregister_owner(self, owner: str) -> int:
        return 1 if self._specs.pop(owner, None) is not None else 0

    def owners(self) -> List[str]:
        return [owner for owner, specs in self._specs.items() if specs]

    def specs(self, owner: str = "") -> List[SettingSpec]:
        return list(self._specs.get(owner, []))

    def all_specs(self) -> List[SettingSpec]:
        rows: List[SettingSpec] = []
        for owner in self._specs:
            rows.extend(self._specs[owner])
        return rows

    def find(self, owner: str, key: str) -> Optional[SettingSpec]:
        for spec in self._specs.get(owner, []):
            if spec.key == key:
                return spec
        return None
