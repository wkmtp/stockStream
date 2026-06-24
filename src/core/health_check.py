"""Health Check — 统一健康检查端点。

V3.0 Production: /health 接口，返回所有模块状态 (healthy/warning/critical)。

集成 stream_guard, recovery_manager, resource_manager 的检查结果。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

if __name__ != "__main__":
    from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


class ModuleHealth(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"    # 功能正常但性能下降
    WARNING = "warning"       # 部分功能异常
    CRITICAL = "critical"     # 模块不可用
    UNKNOWN = "unknown"       # 无法获取状态


@dataclass
class ModuleStatus:
    name: str
    health: ModuleHealth = ModuleHealth.UNKNOWN
    last_check: float = 0.0
    uptime_seconds: float = 0.0
    error_count: int = 0
    last_error: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class SystemHealth:
    """全系统健康报告。"""
    status: ModuleHealth = ModuleHealth.HEALTHY
    timestamp: float = 0.0
    uptime_seconds: float = 0.0
    modules: dict[str, ModuleStatus] = field(default_factory=dict)
    resources: dict[str, Any] = field(default_factory=dict)
    stream_health: dict[str, Any] = field(default_factory=dict)


class HealthCheckService:
    """统一健康检查服务。

    被 FastAPI /health 端点调用，聚合所有模块和子系统的健康状态。
    """

    # V3.0: 所有需要监控的模块列表
    MONITORED_MODULES: list[str] = [
        "market_service",
        "selector_service",
        "analysis_service",
        "tts_service",
        "avatar_service",
        "chart_service",
        "subtitle_service",
        "live_page_service",
        "interaction_service",
        "director_agent",
        "operation_agent",
        "monitoring_service",
        "database",
        "redis",
        "websocket",
        "event_bus",
        "stream_guard",
        "recovery_manager",
        "resource_manager",
        "scheduler",
    ]

    def __init__(self, bus: EventBus | None = None) -> None:
        self._bus = bus
        self._started_at: float = time.time()
        self._module_states: dict[str, ModuleStatus] = {}
        for name in self.MONITORED_MODULES:
            self._module_states[name] = ModuleStatus(name=name)
        self._running = False
        self._refresh_task: asyncio.Task | None = None

    # ── Public API ─────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        bus = await self._ensure_bus()

        # 监听各模块状态更新
        bus.on("monitoring.module_status")(self._on_module_status)
        bus.on("stream.health")(self._on_stream_health)

        self._refresh_task = asyncio.create_task(self._refresh_loop())
        logger.info("HealthCheckService started (modules=%d)", len(self.MONITORED_MODULES))

    async def stop(self) -> None:
        self._running = False
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
            self._refresh_task = None
        logger.info("HealthCheckService stopped")

    async def get_full_report(self) -> SystemHealth:
        """生成完整系统健康报告。"""
        overall = ModuleHealth.HEALTHY
        now = time.time()

        # 汇总模块状态
        for status in self._module_states.values():
            if status.health == ModuleHealth.UNKNOWN:
                continue
            if status.health.value == "critical":
                overall = ModuleHealth.CRITICAL
                break
            elif status.health.value == "warning" and overall != ModuleHealth.CRITICAL:
                overall = ModuleHealth.WARNING

        # 汇总资源状态
        resources = await self._collect_resource_metrics()

        # 汇总流健康
        stream_health = self._latest_stream_health or {}

        return SystemHealth(
            status=overall,
            timestamp=now,
            uptime_seconds=now - self._started_at,
            modules=self._module_states.copy(),
            resources=resources,
            stream_health=stream_health,
        )

    async def get_quick_status(self) -> dict:
        """快速状态摘要（轻量，用于负载均衡 / 探活）。"""
        report = await self.get_full_report()
        return {
            "status": report.status.value,
            "uptime_seconds": report.uptime_seconds,
            "module_count": len(report.modules),
            "unhealthy_modules": [
                name for name, s in report.modules.items()
                if s.health in (ModuleHealth.CRITICAL, ModuleHealth.WARNING)
            ],
        }

    def set_module_status(self, name: str, health: ModuleHealth,
                          error: str = "", metrics: dict | None = None) -> None:
        """手动设置模块状态（供外部模块调用）。"""
        if name not in self._module_states:
            self._module_states[name] = ModuleStatus(name=name)
        s = self._module_states[name]
        s.health = health
        s.last_check = time.time()
        s.uptime_seconds = time.time() - self._started_at
        if error:
            s.error_count += 1
            s.last_error = error
        if metrics:
            s.metrics = metrics

    # ── Event handlers ─────────────────────────────────────────────

    async def _on_module_status(self, event) -> None:
        data = event.data or {}
        name = data.get("module", data.get("name", ""))
        if not name:
            return
        health_str = data.get("health", data.get("status", "unknown"))
        try:
            health = ModuleHealth(health_str)
        except ValueError:
            health = ModuleHealth.UNKNOWN
        self.set_module_status(
            name, health,
            error=data.get("error", ""),
            metrics=data.get("metrics"),
        )

    _latest_stream_health: dict = {}

    async def _on_stream_health(self, event) -> None:
        data = event.data or {}
        self._latest_stream_health = {
            "health": data.get("health", "unknown"),
            "checks": data.get("checks", {}),
            "timestamp": time.time(),
        }

    # ── Helpers ────────────────────────────────────────────────────

    async def _refresh_loop(self) -> None:
        """定期刷新模块状态（60s 间隔）。"""
        bus = await self._ensure_bus()
        while self._running:
            try:
                # 对未知状态的模块标记 warning
                now = time.time()
                for name, status in self._module_states.items():
                    if status.health == ModuleHealth.UNKNOWN:
                        status.last_check = now
                        status.uptime_seconds = now - self._started_at

                await bus.emit_async("health_check.report", {
                    "status": (await self.get_quick_status())["status"],
                    "timestamp": now,
                })
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("HealthCheck refresh error: %s", exc)
            await asyncio.sleep(60)

    async def _collect_resource_metrics(self) -> dict:
        """收集系统资源指标。"""
        metrics: dict = {}
        try:
            import psutil
            metrics["cpu_percent"] = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            metrics["memory_percent"] = mem.percent
            metrics["memory_used_gb"] = round(mem.used / (1024**3), 2)
            metrics["memory_total_gb"] = round(mem.total / (1024**3), 2)
            disk = psutil.disk_usage("/")
            metrics["disk_percent"] = disk.percent
            metrics["disk_free_gb"] = round(disk.free / (1024**3), 2)
        except ImportError:
            metrics["note"] = "psutil not installed"
        except Exception as exc:
            metrics["error"] = str(exc)
        return metrics

    async def _ensure_bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus
