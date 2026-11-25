"""GUI 的「应用套壳」：用系统自带的 Edge/Chrome 以 app 模式开一个无地址栏窗口。

为什么不自己画界面（tkinter）：那套控件视觉太旧。这里用 Chromium 渲染同一个控制台
（framework/gui/index.html），窗口没有地址栏、没有标签页，关掉窗口就等于退出程序。

找不到 Edge/Chrome 时退回默认浏览器（功能一样，只是带地址栏）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from framework.logging import get

log = get("gui.window")

CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)


def find_browser() -> Optional[str]:
    for path in CANDIDATES:
        if Path(path).exists():
            return path
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        for suffix in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
            candidate = Path(local) / suffix
            if candidate.exists():
                return str(candidate)
    return None


class AppWindow:
    """把控制台 URL 装进一个没有地址栏的窗口。"""

    def __init__(self, profile_dir: Path, size: str = "1280x840") -> None:
        self.profile_dir = Path(profile_dir)
        self.size = size

    def command(self, url: str, browser: Optional[str] = None) -> List[str]:
        exe = browser or find_browser()
        if not exe:
            return []
        return [
            exe,
            "--app=" + url,
            "--window-size=" + self.size,
            "--user-data-dir=" + str(self.profile_dir),
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-background-networking",
        ]

    def open_blocking(self, url: str) -> str:
        """打开窗口并阻塞到关窗；返回实际使用的形态（app / browser）。"""
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        cmd = self.command(url)
        if not cmd:
            log.warning("没有找到 Edge/Chrome，退回默认浏览器")
            import webbrowser

            webbrowser.open(url)
            return "browser"
        log.info("app window: %s", url)
        creation = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0
        try:
            process = subprocess.Popen(cmd, creationflags=creation)
            process.wait()
        except Exception as error:  # noqa: BLE001 - 起不来就退回浏览器
            log.warning("app window failed (%s); using default browser", error)
            import webbrowser

            webbrowser.open(url)
            return "browser"
        return "app"
