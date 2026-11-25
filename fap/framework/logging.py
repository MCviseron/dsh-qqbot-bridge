"""统一日志：控制台 + 按天轮转的文件。"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_configured = False


def configure(
    level: int = logging.INFO,
    log_dir: Optional[Path] = None,
    *,
    filename: str = "fap.log",
    force: bool = False,
) -> logging.Logger:
    global _configured
    root = logging.getLogger()
    if _configured and not force:
        return logging.getLogger("fap")
    for handler in list(root.handlers):
        root.removeHandler(handler)
    formatter = logging.Formatter(_FORMAT)
    console = logging.StreamHandler(stream=sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)
    if log_dir is not None:
        try:
            Path(log_dir).mkdir(parents=True, exist_ok=True)
            rotating = logging.handlers.RotatingFileHandler(
                Path(log_dir) / filename, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
            )
            rotating.setFormatter(formatter)
            root.addHandler(rotating)
        except OSError:
            pass
    root.setLevel(level)
    _configured = True
    return logging.getLogger("fap")


def shutdown() -> None:
    """关闭所有文件句柄（测试/退出时用，Windows 下不关会占用日志文件）。"""
    root = logging.getLogger()
    for handler in list(root.handlers):
        try:
            handler.close()
        except Exception:  # noqa: BLE001
            pass
        root.removeHandler(handler)
    global _configured
    _configured = False


def get(name: str) -> logging.Logger:
    return logging.getLogger("fap." + name if not name.startswith("fap") else name)
