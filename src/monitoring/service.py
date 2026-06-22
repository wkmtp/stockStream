"""系统监控服务。"""
from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass, field
from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


@dataclass
class HealthCheck:
    module: str
    healthy: bool
    message: str = ""
    last_check: float = 0.0

    def to_dict(self) -> dict:
        return {
            "module": self.module, "healthy": self.healthy,
            "message": self.message, "last_check": self.last_check,
        }


class MonitoringService:
    """系统监控服务。

    推送事件:
      monitoring.health    — 健康检查结果
      monitoring.alert     — 告警
    """

    def __init__(self, bus: EventBus | None = None) -> None:
        self._bus: EventBus | None = bus
        self._modules: dict[str, callable] = {}  # module_name → health_check_fn
        self._started_at = time.time()
        self._task: asyncio.Task | None = None
        self._running = False

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    def register(self, name: str, health_fn: callable) -> None:
        self._modules[name] = health_fn

    async def start(self, interval: float = 30.0) -> None:
        self._running = True
        self._task = asyncio.create_task(self._loop(interval))
        logger.info("MonitoringService started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("MonitoringService stopped")

    async def _loop(self, interval: float) -> None:
        bus = await self.bus
        while self._running:
            for name, fn in self._modules.items():
                try:
                    healthy, msg = await fn() if asyncio.iscoroutinefunction(fn) else fn()
                    if not healthy:
                        await bus.emit_async("monitoring.alert", {
                            "module": name, "message": msg,
                        })
                except Exception as exc:
                    await bus.emit_async("monitoring.alert", {
                        "module": name, "message": str(exc),
                    })
            await asyncio.sleep(interval)

    async def check_all(self) -> list[HealthCheck]:
        results = []
        for name, fn in self._modules.items():
            try:
                result = await fn() if asyncio.iscoroutinefunction(fn) else fn()
                healthy, msg = result if isinstance(result, tuple) else (result, "")
                results.append(HealthCheck(name, healthy, msg))
            except Exception as exc:
                results.append(HealthCheck(name, False, str(exc)))
        return results

    def uptime_seconds(self) -> float:
        return time.time() - self._started_at
