"""事件总线与存储：通配、优先级、插件级摘除、原子写。"""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from framework.events import EventBus
from framework.storage import JsonStore, JsonlStore


class EventBusTest(unittest.TestCase):
    def test_order_and_wildcard(self) -> None:
        bus = EventBus()
        order = []

        async def low(event="", **payload):
            order.append("low")

        async def high(event="", **payload):
            order.append("high")

        async def wild(event="", **payload):
            order.append("wild:" + event)

        bus.on("tick", low, priority=10)
        bus.on("tick", high, priority=1)
        bus.on("tick", wild, priority=5)
        asyncio.run(bus.emit("tick"))
        self.assertEqual(order, ["high", "wild:tick", "low"])

    def test_handler_error_isolated(self) -> None:
        bus = EventBus()
        seen = []

        async def boom(event="", **payload):
            raise RuntimeError("坏了")

        async def ok(event="", **payload):
            seen.append(True)

        bus.on("x", boom)
        bus.on("x", ok)
        asyncio.run(bus.emit("x"))
        self.assertEqual(seen, [True])

    def test_off_plugin(self) -> None:
        bus = EventBus()

        async def handler(event="", **payload):
            return None

        bus.on("a", handler, plugin="p1")
        bus.on("a", handler, plugin="p2")
        self.assertEqual(bus.off_plugin("p1"), 1)
        self.assertEqual(len(bus.handlers("a")), 1)


class StorageTest(unittest.TestCase):
    def test_json_store_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = JsonStore(Path(folder) / "data.json", {"counter": 0})
            self.assertEqual(store.get("counter"), 0)
            store.update(lambda data: data.__setitem__("counter", data["counter"] + 1))
            self.assertEqual(store.get("counter"), 1)
            on_disk = json.loads((Path(folder) / "data.json").read_text(encoding="utf-8"))
            self.assertEqual(on_disk["counter"], 1)

    def test_json_store_survives_bad_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "broken.json"
            path.write_text("{not json", encoding="utf-8")
            store = JsonStore(path, {"ok": True})
            self.assertEqual(store.read(), {"ok": True})

    def test_jsonl_append_and_tail(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            log = JsonlStore(Path(folder) / "events")
            for index in range(5):
                log.append({"i": index})
            rows = log.tail(3)
            self.assertEqual([row["i"] for row in rows], [2, 3, 4])
            self.assertEqual(len(log.days()), 1)


if __name__ == "__main__":
    unittest.main()
