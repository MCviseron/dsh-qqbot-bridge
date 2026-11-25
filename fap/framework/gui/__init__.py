"""GUI 版本：给框架加一个本地面板。

非 GUI 版本（--no-gui）根本不会 import 这个包，因此不装 aiohttp 也能跑机器人。
"""

from framework.gui.panel import Panel

__all__ = ["Panel"]
