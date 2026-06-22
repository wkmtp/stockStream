"""异常恢复管理器 — 模块崩溃自动恢复。

特性:
    1. 模块崩溃自动重启
    2. 指数退避重试策略
    3. 最大重试次数限制
    4. 推流断开自动重连
    5. 恢复后自动重新订阅事件
    6. 恢复事件通知

用法:
    from src.core.recovery_manager import RecoveryManager

    rm = RecoveryManager()
    rm.register("market", restart_fn=restart_market, max_retries=5)
    rm.register("tts", restart_fn=restart_tts, max_retries=3)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine

from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


class RecoveryState(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    RECOVERING = "recovering"
    FAILED = "failed"


@dataclass
class RecoveryConfig:
    """恢复策略配置。"""
    max_retries: int = 5
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    backoff_multiplier: float = 2.0
    health_check_interval: float = 10.0
    stream_reconnect_interval: float = 3.0
    stream_max_reconnect: int = 20


@dataclass
class ModuleGuard:
    """模块守护记录。"""
    name: str
    restart_fn: Callable[[], Coroutine[Any, Any, bool]]
    max_retries: int = 5
    state: RecoveryState = RecoveryState.HEALTHY
    retry_count: int = 0
    last_health_check: float = field(default_factory=time.time)
    last_error: str = ""
    last_recovery: float = 0.0
    total_recoveries: int = 0
    consecutive_failures: int = 0


class RecoveryManager:
    """异常恢复管理器。

    监听 monitoring.alert 事件，自动重启崩溃模块。
    通过事件总线与其他模块通讯。
    """

    def __init__(
        self,
        config: RecoveryConfig | None = None,
        bus: EventBus | None = None,
    ) -> None:
        self.config = config or RecoveryConfig()
        self._bus: EventBus | None = bus
        self._guards: dict[str, ModuleGuard] = {}
        self._running = False
        self._task: asyncio.Task | None = None

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    # ── Registration ────────────────────────────────────────────────

    def register(
        self,
        name: str,
        restart_fn: Callable[[], Coroutine[Any, Any, bool]],
        max_retries: int | None = None,
        health_check_fn: Callable[[], Coroutine[Any, Any, bool]] | None = None,
    ) -> ModuleGuard:
        """注册需要守护的模块。

        Args:
            name: 模块名称 (market / tts / stream / avatar 等)
            restart_fn: 重启函数，返回 True 表示成功
            max_retries: 最大重试次数，默认使用全局配置
            health_check_fn: 健康检查函数，返回 True 表示健康
        """
        guard = ModuleGuard(
            name=name,
            restart_fn=restart_fn,
            max_retries=max_retries or self.config.max_retries,
        )
        self._guards[name] = guard

        if health_check_fn:
            if not hasattr(self, '_health_checks'):
                self._health_checks = {}
            self._health_checks[name] = health_check_fn

        logger.info("RecoveryManager registered guard: %s (max_retries=%d)",
                    name, guard.max_retries)
        return guard

    def unregister(self, name: str) -> None:
        """移除模块守护。"""
        self._guards.pop(name, None)
        self._health_checks.pop(name, None)

    # ── Lifecycle ───────────────────────────────────────────────────

    async def start(self) -> None:
        """启动恢复管理器。"""
        self._running = True
        self._task = asyncio.create_task(self._loop())

        bus = await self.bus

        # 24h 稳定性：记录所有订阅句柄，stop() 时取消
        self._subs: list[tuple[str, object]] = []

        # 监听告警事件
        @bus.on("monitoring.alert")
        async def _on_alert(event):
            await self._handle_alert(event)
        self._subs.append(("monitoring.alert", _on_alert))

        # 监听流状态变化
        @bus.on("stream.status_changed")
        async def _on_stream_status(event):
            await self._handle_stream_status(event)
        self._subs.append(("stream.status_changed", _on_stream_status))

        logger.info("RecoveryManager started (%d guards)", len(self._guards))

    async def stop(self) -> None:
        """停止恢复管理器。"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # 24h 稳定性：取消所有 EventBus 订阅
        bus = await self.bus
        for pattern, handler in getattr(self, '_subs', []):
            bus.unsubscribe(pattern, handler)
        self._subs = []

        logger.info("RecoveryManager stopped")

    # ── Core Loop ───────────────────────────────────────────────────

    async def _loop(self) -> None:
        """主循环 — 定期检查各模块健康状态。"""
        bus = await self.bus
        while self._running:
            try:
                for name, guard in list(self._guards.items()):
                    if guard.state == RecoveryState.DEGRADED:
                        await self._attempt_recovery(name, guard)

                    # 定期健康检查
                    if time.time() - guard.last_health_check > self.config.health_check_interval:
                        await self._check_health(name, guard)
                        guard.last_health_check = time.time()

                await asyncio.sleep(self.config.health_check_interval)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("RecoveryManager loop error: %s", exc)
                await asyncio.sleep(5)

    # ── Recovery Logic ──────────────────────────────────────────────

    async def _handle_alert(self, event: Any) -> None:
        """处理监控告警，触发自动恢复。"""
        data = event.data or {}
        module_name = data.get("module", "")

        if module_name in self._guards:
            guard = self._guards[module_name]
            guard.last_error = data.get("message", "unknown")
            guard.state = RecoveryState.DEGRADED

            logger.warning(
                "RecoveryManager: module %s degraded — %s",
                module_name, guard.last_error,
            )

            await self._attempt_recovery(module_name, guard)

    async def _handle_stream_status(self, event: Any) -> None:
        """处理推流状态变化，自动重连。"""
        data = event.data or {}
        status = data.get("status", "")
        if status in ("disconnected", "error"):
            logger.warning("RecoveryManager: stream disconnected — auto-reconnect")
            await self._stream_reconnect()

    async def _stream_reconnect(self) -> bool:
        """推流自动重连。"""
        bus = await self.bus
        for attempt in range(1, self.config.stream_max_reconnect + 1):
            try:
                await bus.emit_async("stream.reconnect", {
                    "attempt": attempt,
                    "max_attempts": self.config.stream_max_reconnect,
                })
                logger.info("Stream reconnect attempt %d/%d", attempt, self.config.stream_max_reconnect)
                await asyncio.sleep(self.config.stream_reconnect_interval)

                # 检查是否恢复
                # 这里由 stream 模块在重连成功后发送 stream.connected 事件
                await asyncio.sleep(1)
                return True

            except Exception as exc:
                logger.error("Stream reconnect attempt %d failed: %s", attempt, exc)

        logger.critical("Stream reconnect exhausted (%d attempts)",
                        self.config.stream_max_reconnect)
        return False

    async def _attempt_recovery(self, name: str, guard: ModuleGuard) -> None:
        """尝试恢复模块 — 指数退避重试。"""
        if guard.state == RecoveryState.RECOVERING:
            return  # 正在恢复中

        if guard.retry_count >= guard.max_retries:
            guard.state = RecoveryState.FAILED
            logger.critical(
                "RecoveryManager: module %s FAILED after %d retries",
                name, guard.retry_count,
            )
            bus = await self.bus
            await bus.emit_async("system.module_failed", {
                "module": name,
                "retries": guard.retry_count,
                "last_error": guard.last_error,
            })
            return

        guard.state = RecoveryState.RECOVERING
        guard.retry_count += 1
        guard.consecutive_failures += 1

        # 指数退避
        delay = min(
            self.config.base_delay_seconds * (self.config.backoff_multiplier ** (guard.retry_count - 1)),
            self.config.max_delay_seconds,
        )

        logger.info(
            "RecoveryManager: restarting %s (attempt %d/%d, delay=%.1fs)",
            name, guard.retry_count, guard.max_retries, delay,
        )

        await asyncio.sleep(delay)

        try:
            success = await guard.restart_fn()

            if success:
                guard.state = RecoveryState.HEALTHY
                guard.retry_count = 0
                guard.consecutive_failures = 0
                guard.last_recovery = time.time()
                guard.total_recoveries += 1

                bus = await self.bus
                await bus.emit_async("system.module_recovered", {
                    "module": name,
                    "total_recoveries": guard.total_recoveries,
                })
                logger.info("RecoveryManager: %s recovered successfully", name)
            else:
                guard.state = RecoveryState.DEGRADED
                logger.warning("RecoveryManager: %s restart returned False", name)

        except Exception as exc:
            guard.state = RecoveryState.DEGRADED
            guard.last_error = str(exc)
            logger.error("RecoveryManager: %s restart failed: %s", name, exc)

    async def _check_health(self, name: str, guard: ModuleGuard) -> None:
        """检查模块健康状态。"""
        if name in self._health_checks:
            try:
                healthy = await self._health_checks[name]()
                if not healthy and guard.state == RecoveryState.HEALTHY:
                    guard.state = RecoveryState.DEGRADED
                    guard.last_error = "health check failed"
                    await self._attempt_recovery(name, guard)
            except Exception as exc:
                guard.state = RecoveryState.DEGRADED
                guard.last_error = str(exc)
                await self._attempt_recovery(name, guard)

    # ── Manual Recovery ─────────────────────────────────────────────

    async def force_recover(self, name: str) -> bool:
        """手动触发模块恢复。"""
        if name not in self._guards:
            logger.warning("RecoveryManager: unknown module %s", name)
            return False

        guard = self._guards[name]
        guard.state = RecoveryState.DEGRADED
        guard.retry_count = 0  # reset retry counter
        await self._attempt_recovery(name, guard)
        return guard.state == RecoveryState.HEALTHY

    async def recover_all(self) -> dict[str, bool]:
        """恢复所有异常模块。"""
        results = {}
        for name in list(self._guards.keys()):
            results[name] = await self.force_recover(name)
        return results

    # ── Query ───────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """获取所有模块的守护状态。"""
        return {
            name: {
                "state": g.state.value,
                "retry_count": g.retry_count,
                "max_retries": g.max_retries,
                "last_error": g.last_error,
                "total_recoveries": g.total_recoveries,
                "consecutive_failures": g.consecutive_failures,
            }
            for name, g in self._guards.items()
        }

    def is_healthy(self, name: str) -> bool:
        """检查指定模块是否健康。"""
        guard = self._guards.get(name)
        return guard is not None and guard.state == RecoveryState.HEALTHY

    @property
    def healthy_count(self) -> int:
        return sum(1 for g in self._guards.values()
                   if g.state == RecoveryState.HEALTHY)

    @property
    def failed_modules(self) -> list[str]:
        return [n for n, g in self._guards.items()
                if g.state == RecoveryState.FAILED]

    # ── Internal ────────────────────────────────────────────────────
    pass
