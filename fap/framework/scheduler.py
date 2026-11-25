"""轻量定时器：插件注册周期任务，框架统一收口异常。"""

from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List

from framework.logging import get

log = get("scheduler")


@dataclass
class Job:
    name: str
    interval: float
    handler: Callable[[], Any]
    plugin: str = ""
    run_immediately: bool = False
    task: Any = None
    last: float = 0.0
    runs: int = 0
    errors: int = 0
    field_meta: Dict[str, Any] = field(default_factory=dict)


class Scheduler:
    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._running = False

    def every(
        self,
        name: str,
        interval: float,
        handler: Callable[[], Any],
        *,
        plugin: str = "",
        run_immediately: bool = False,
    ) -> Job:
        job = Job(
            name=name,
            interval=max(1.0, float(interval)),
            handler=handler,
            plugin=plugin,
            run_immediately=run_immediately,
        )
        self._jobs[name] = job
        if self._running:
            job.task = asyncio.create_task(self._loop(job), name="job:" + name)
        return job

    def cancel(self, name: str) -> None:
        job = self._jobs.pop(name, None)
        if job is not None and job.task is not None:
            job.task.cancel()

    def cancel_plugin(self, plugin: str) -> int:
        names = [job.name for job in self._jobs.values() if job.plugin == plugin]
        for name in names:
            self.cancel(name)
        return len(names)

    def jobs(self) -> List[Job]:
        return list(self._jobs.values())

    async def _loop(self, job: Job) -> None:
        if not job.run_immediately:
            await asyncio.sleep(job.interval)
        while True:
            try:
                outcome = job.handler()
                if inspect.isawaitable(outcome):
                    await outcome
                job.runs += 1
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - 定时任务不能拖垮框架
                job.errors += 1
                log.exception("job %s failed: %s", job.name, error)
            job.last = time.time()
            await asyncio.sleep(job.interval)

    async def start(self) -> None:
        self._running = True
        for job in self._jobs.values():
            if job.task is None or job.task.done():
                job.task = asyncio.create_task(self._loop(job), name="job:" + job.name)

    async def stop(self) -> None:
        self._running = False
        for job in self._jobs.values():
            if job.task is not None:
                job.task.cancel()
                job.task = None
