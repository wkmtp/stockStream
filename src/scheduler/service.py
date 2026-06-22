"""定时调度服务。"""
from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Callable, Coroutine

from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


@dataclass
class ScheduledTask:
    name: str
    func: Callable[[], Coroutine]
    interval_seconds: float
    enabled: bool = True
    last_run: float = 0.0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "interval_seconds": self.interval_seconds,
            "enabled": self.enabled,
            "last_run": self.last_run,
        }


class SchedulerService:
    """定时调度服务。

    推送事件:
      scheduler.task_run     — 任务执行
      scheduler.task_error   — 任务错误
    """

    def __init__(self, bus: EventBus | None = None) -> None:
        self._bus: EventBus | None = bus
        self._tasks: dict[str, ScheduledTask] = {}
        self._running = False
        self._loop_task: asyncio.Task | None = None

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    def add_task(self, name: str, func: Callable[[], Coroutine],
                 interval_seconds: float) -> None:
        self._tasks[name] = ScheduledTask(
            name=name, func=func, interval_seconds=interval_seconds,
        )

    async def start(self) -> None:
        self._running = True
        logger.info("SchedulerService started with %d tasks", len(self._tasks))

        async def _run_loop():
            bus = await self.bus
            while self._running:
                import time
                now = time.time()
                for task in list(self._tasks.values()):
                    if not task.enabled:
                        continue
                    if now - task.last_run >= task.interval_seconds:
                        try:
                            await task.func()
                            task.last_run = now
                            await bus.emit_async("scheduler.task_run", {
                                "task": task.name,
                            })
                        except Exception as exc:
                            logger.error("Scheduled task %s failed: %s", task.name, exc)
                            await bus.emit_async("scheduler.task_error", {
                                "task": task.name, "error": str(exc),
                            })
                await asyncio.sleep(1.0)

        self._loop_task = asyncio.create_task(_run_loop())

    async def stop(self) -> None:
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        logger.info("SchedulerService stopped")

    def get_tasks(self) -> list[dict]:
        return [t.to_dict() for t in self._tasks.values()]
