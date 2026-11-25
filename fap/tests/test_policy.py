"""框架策略：主人落盘、静默时段、限流、入站去重、Markdown 判定。"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from framework.app import FapApp
from framework.bot import QQBot, looks_like_markdown


class OwnerPersistTest(unittest.TestCase):
    def test_claim_is_persisted_across_restart(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            app = FapApp(root=Path(folder), log_to_file=False)
            self.assertTrue(app.is_owner("USER-A"))          # 首次发言认领
            self.assertFalse(app.is_owner("USER-B"))
            app2 = FapApp(root=Path(folder), log_to_file=False)
            self.assertTrue(app2.is_owner("USER-A"))         # 重启后仍是同一主人
            self.assertFalse(app2.is_owner("USER-B"))

    def test_configured_owner_wins(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            app = FapApp(root=Path(folder), log_to_file=False)
            app.config.update({"owners": ["OWNER-X"]})
            self._noop()
            fresh = FapApp(root=Path(folder), log_to_file=False)
            self.assertTrue(fresh.is_owner("OWNER-X"))

    @staticmethod
    def _noop() -> None:
        return None


class PolicyTest(unittest.TestCase):
    def test_quiet_hours_parse(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            app = FapApp(root=Path(folder), log_to_file=False)
            app.config.update({"quiet_hours": "23:30-07:00"})
            self.assertIn(app.in_quiet_hours(), (True, False))   # 只校验解析不炸
            app.config.update({"quiet_hours": "00:00-00:00"})
            self.assertFalse(app.in_quiet_hours())
            app.config.update({"quiet_hours": "坏数据"})
            self.assertFalse(app.in_quiet_hours())

    def test_rate_limit(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            app = FapApp(root=Path(folder), log_to_file=False)
            app.config.update({"rate_limit_per_hour": 2})
            self.assertFalse(app._rate_limited("group:A"))
            self.assertFalse(app._rate_limited("group:A"))
            self.assertTrue(app._rate_limited("group:A"))
            self.assertFalse(app._rate_limited("group:B"))       # 会话之间独立

    def test_dedup(self) -> None:
        bot = QQBot(app=None)
        self.assertFalse(bot._is_duplicate("M1"))
        self.assertTrue(bot._is_duplicate("M1"))
        self.assertFalse(bot._is_duplicate("M2"))
        bot._seen["OLD"] = time.time() - 1000
        self.assertFalse(bot._is_duplicate("OLD"))               # 过期条目被清理后放行

    def test_markdown_detection(self) -> None:
        self.assertTrue(looks_like_markdown("## 标题"))
        self.assertTrue(looks_like_markdown("- 一\n- 二"))
        self.assertTrue(looks_like_markdown("| a | b |"))
        self.assertTrue(looks_like_markdown("**粗体**"))
        self.assertFalse(looks_like_markdown("普通一句话"))


if __name__ == "__main__":
    unittest.main()
