"""分层配置：代码默认值 ← 配置文件 ← 环境变量。

配置文件按 mtime 自动热加载（不重启也能改），与既有项目 runtime_config.py 的
行为保持一致，但去掉了业务字段——框架只认框架自己的键，业务键由插件声明。
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

DEFAULTS: Dict[str, Any] = {
    # --- 连接 ---
    "appid": "",
    "appsecret": "",
    "token": "",                  # 部分部署需要；留空则由 appid/secret 换取
    "sandbox": False,
    "connect_qq": True,        # 插件托管旧机器人时应设 false，避免两条网关抢 AppID
    # --- 框架行为 ---
    "botname": "机器人",
    "aliases": ["机器人"],
    "owners": [],                 # 主人 openid 列表（首个发言人自动认领可用 claim_owner）
    "claim_owner": True,
    "command_prefix": "/",
    "group_enabled": True,
    "c2c_enabled": True,
    "allowlist_groups": [],
    "allowlist_c2c": [],
    "max_chars": 1500,
    "debounce_ms": 0,
    "rate_limit_per_hour": 0,
    "quiet_hours": "",
    "plugins_dir": "plugins",
    "enabled_plugins": [],        # 空 = 全部启用
    "state_dir": "session/state",
    "log_dir": "session/logs",
    # --- GUI ---
    "gui": False,
    "gui_host": "127.0.0.1",
    "gui_port": 39080,
    "gui_token": "",
}

ENV_PREFIX = "FAP_"


def _coerce(value: Any, reference: Any) -> Any:
    """按默认值的类型把环境变量字符串转回来。"""
    if isinstance(reference, bool):
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(reference, int) and not isinstance(reference, bool):
        try:
            return int(str(value).strip())
        except ValueError:
            return reference
    if isinstance(reference, float):
        try:
            return float(str(value).strip())
        except ValueError:
            return reference
    if isinstance(reference, list):
        return [item.strip() for item in str(value).split(",") if item.strip()]
    return value


class Config:
    """线程安全的配置视图。

    * get("a")                → 顶层键
    * get("plugins.x.y", d)   → 插件命名空间（点号路径）
    """

    def __init__(self, path: Path, defaults: Optional[Mapping[str, Any]] = None) -> None:
        self.path = Path(path)
        self._defaults: Dict[str, Any] = dict(DEFAULTS)
        if defaults:
            self._defaults.update(defaults)
        self._data: Dict[str, Any] = dict(self._defaults)
        self._mtime = 0.0
        self._lock = threading.RLock()
        self.reload(force=True)

    # -- 读取 ---------------------------------------------------------------
    def reload(self, *, force: bool = False) -> bool:
        with self._lock:
            data = dict(self._defaults)
            if self.path.exists():
                try:
                    mtime = self.path.stat().st_mtime
                except OSError:
                    mtime = 0.0
                if not force and mtime == self._mtime:
                    return False
                try:
                    loaded = json.loads(self.path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    loaded = {}
                if isinstance(loaded, dict):
                    data.update(loaded)
                self._mtime = mtime
            self._data = self._apply_env(data)
            return True

    @staticmethod
    def _apply_env(data: Dict[str, Any]) -> Dict[str, Any]:
        for key, reference in list(data.items()):
            raw = os.environ.get(ENV_PREFIX + key.upper())
            if raw is not None:
                data[key] = _coerce(raw, reference)
        return data

    def get(self, dotted: str, default: Any = None) -> Any:
        self.reload()
        with self._lock:
            node: Any = self._data
            for part in str(dotted).split("."):
                if isinstance(node, dict) and part in node:
                    node = node[part]
                else:
                    return default
            return node

    def section(self, name: str) -> Dict[str, Any]:
        """插件配置段：plugins.<id>。（不存在时返回空字典）"""
        value = self.get("plugins." + name, {})
        return dict(value) if isinstance(value, dict) else {}

    def snapshot(self, *, mask_secrets: bool = True) -> Dict[str, Any]:
        self.reload()
        with self._lock:
            data = json.loads(json.dumps(self._data, ensure_ascii=False))
        if mask_secrets:
            for key in ("appsecret", "token", "gui_token"):
                if data.get(key):
                    data[key] = "***"
        return data

    # -- 写入 ---------------------------------------------------------------
    def update(self, patch: Mapping[str, Any]) -> Dict[str, Any]:
        """浅合并写入文件并立刻生效（插件段用 {"plugins": {...}} 整体覆盖）。"""
        self.reload()
        with self._lock:
            current = json.loads(json.dumps(self._data, ensure_ascii=False))
        for key, value in (patch or {}).items():
            if key == "plugins" and isinstance(value, dict):
                merged = current.get("plugins") if isinstance(current.get("plugins"), dict) else {}
                for plugin_id, section in value.items():
                    if isinstance(section, dict) and isinstance(merged.get(plugin_id), dict):
                        merged[plugin_id].update(section)
                    else:
                        merged[plugin_id] = section
                current["plugins"] = merged
            else:
                current[key] = value
        # 默认值不写进文件，保持文件干净
        current = {key: value for key, value in current.items() if key not in ("gui",) or value}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)
        self.reload(force=True)
        return self.snapshot()

    def owner_ids(self) -> Iterable[str]:
        owners = self.get("owners", [])
        if isinstance(owners, str):
            owners = [item.strip() for item in owners.split(",") if item.strip()]
        return [str(item) for item in (owners or []) if str(item).strip()]


def config_path(root: Path, name: str = "config.json") -> Path:
    return Path(root) / name
