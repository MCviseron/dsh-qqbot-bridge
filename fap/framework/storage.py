"""小型持久化：JSON 键值 + JSONL 追加。

设计原则：原子写（写 .tmp 再 replace）、读写失败不抛给调用方、线程内加锁。
插件的数据默认落在 session/state/<plugin_id>/ 下。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


class JsonStore:
    """一个 JSON 文件当成字典用。"""

    def __init__(self, path: Path, default: Optional[Dict[str, Any]] = None) -> None:
        self.path = Path(path)
        self._default = dict(default or {})
        self._lock = threading.RLock()

    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return json.loads(json.dumps(self._default))
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return json.loads(json.dumps(self._default))
        return data if isinstance(data, dict) else json.loads(json.dumps(self._default))

    def read(self) -> Dict[str, Any]:
        with self._lock:
            return self._load()

    def write(self, data: Dict[str, Any]) -> None:
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_suffix(self.path.suffix + ".tmp")
                temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                temporary.replace(self.path)
            except OSError:
                pass

    def update(self, changer: Callable[[Dict[str, Any]], Any]) -> Dict[str, Any]:
        """读-改-写一把锁内完成：update(lambda data: data.setdefault("x", 0) + 1)"""
        with self._lock:
            data = self._load()
            changer(data)
            self.write(data)
            return data

    def get(self, key: str, default: Any = None) -> Any:
        return self.read().get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.update(lambda data: data.__setitem__(key, value))


class JsonlStore:
    """按天切分的追加日志（仪表盘/统计用）。"""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def path_for(self, day: Optional[str] = None) -> Path:
        stamp = day or time.strftime("%Y-%m-%d")
        return self.directory / (stamp + ".jsonl")

    def append(self, record: Dict[str, Any], day: Optional[str] = None) -> None:
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with self.path_for(day).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def tail(self, limit: int = 100, day: Optional[str] = None) -> List[Dict[str, Any]]:
        path = self.path_for(day)
        if not path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
        except OSError:
            return []
        return rows[-limit:]

    def days(self, limit: int = 7) -> List[str]:
        try:
            return sorted(path.stem for path in self.directory.glob("*.jsonl"))[-limit:]
        except OSError:
            return []
