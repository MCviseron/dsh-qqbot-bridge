"""Runtime settings shared by the supervisor, the bot and the settings page.

Stored as bot/config.json and re-read when its mtime changes, so the panel can
flip switches without restarting anything. Keys here are behaviour-level: secrets
may be overridden too, but those only take effect when the bot process restarts.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

DEFAULTS: Dict[str, Any] = {
    # 总开关与分渠道开关
    "enabled": True,
    "c2c_enabled": True,
    "group_enabled": True,
    # 群聊行为
    "group_full_mode": True,
    "chatter_batch": 4,
    "chatter_max_s": 60,
    "chatter_cooldown_s": 90,
    "bot_say_memory_s": 300,
    "stuck_turn_s": 180,
    # 发送行为
    "md_auto": True,
    "ack_delay_s": 5,
    "debounce_ms": 700,
    "debounce_max_ms": 3000,
    "max_chars": 1600,
    # 群聊过滤与插话边界
    "group_allowlist": "",
    "c2c_allowlist": "",
    "bot_aliases": "蓝色大肥鱼,大肥鱼,机器人,DSH,dsh",
    "quiet_hours": "",
    # 消息池（引用解析 + /撤回 + 插话判断的上下文窗口）
    "pool_ttl_s": 1800,
    "pool_max": 100,
    # 引用消息：识别开关、随提示词带给模型的原文上限、排查日志
    "quote_enabled": True,
    "quote_context_chars": 300,
    "quote_probe": False,
    # 流式（平台只支持单聊）
    "stream_enabled": False,
    "stream_mode": "api",
    "stream_interval_ms": 500,
    "stream_min_chars": 14,
    "stream_max_chunks": 6,
    # 图片与文件
    "image_max_mb": 8,
    "image_cache_s": 120,
    "capture_enabled": True,
    # 频率限制：每个会话每小时最多回多少条，0=不限
    "rate_limit_per_hour": 0,
    # 桥接（改完需重启机器人）
    "bridge_url": "http://127.0.0.1:39061",
    "bridge_token": "",
    # 设置页
    "panel_host": "127.0.0.1",
    "panel_port": 39062,
    # 进程守护
    "desired_running": True,
    # 凭据覆盖（留空则用 .env）
    "appid": "",
    "appsecret": "",
}

SECRET_KEYS = {"appsecret"}


class RuntimeConfig:
    """Small mtime-watched JSON config with defaults."""

    def __init__(self, path: Path = CONFIG_PATH) -> None:
        self.path = path
        self._data: Dict[str, Any] = dict(DEFAULTS)
        self._mtime = 0.0
        self.reload(force=True)

    def reload(self, *, force: bool = False) -> bool:
        """Reload when the file changed; returns True when values were refreshed."""
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return False
        if not force and mtime == self._mtime:
            return False
        try:
            parsed = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(parsed, dict):
            return False
        data = dict(DEFAULTS)
        data.update({key: value for key, value in parsed.items() if key in DEFAULTS})
        self._data = data
        self._mtime = mtime
        return True

    # -- typed access ------------------------------------------------------- #
    def get(self, key: str) -> Any:
        self.reload()
        return self._data.get(key, DEFAULTS.get(key))

    def get_bool(self, key: str) -> bool:
        value = self.get(key)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def get_int(self, key: str) -> int:
        try:
            return int(self.get(key))
        except (TypeError, ValueError):
            return int(DEFAULTS[key])

    def get_float(self, key: str) -> float:
        try:
            return float(self.get(key))
        except (TypeError, ValueError):
            return float(DEFAULTS[key])

    def snapshot(self, *, mask_secrets: bool = True) -> Dict[str, Any]:
        self.reload()
        data = dict(self._data)
        if mask_secrets:
            for key in SECRET_KEYS:
                value = str(data.get(key) or "")
                data[key] = (value[:4] + "****" + value[-2:]) if len(value) > 6 else ("****" if value else "")
        return data

    def update(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        """Persist a partial update; unknown keys and blank secrets are ignored."""
        current = self.snapshot(mask_secrets=False)
        for key, value in (patch or {}).items():
            if key not in DEFAULTS:
                continue
            if key in SECRET_KEYS and isinstance(value, str) and value.strip() == "":
                continue
            current[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)
        self.reload(force=True)
        return self.snapshot()
