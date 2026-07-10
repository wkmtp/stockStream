"""Resource Manager — 通用资源管理器。

V3.0 Production: 监控 CPU/GPU/内存/磁盘/网络，自动保护系统。
  内存超过 80% → 自动清理缓存
  GPU 超过 90% → 暂停非关键任务
  记录告警并通知监控系统。

与 Jetson 特定优化 (jetson_optimizer.py) 配合使用。
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum

if __name__ != "__main__":
    from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


class ResourceLevel(Enum):
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class ResourceSnapshot:
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_used_gb: float = 0.0
    memory_total_gb: float = 0.0
    gpu_percent: float = 0.0
    gpu_memory_mb: float = 0.0
    disk_percent: float = 0.0
    disk_free_gb: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class ResourceConfig:
    # 阈值
    memory_warning_pct: float = 70.0
    memory_critical_pct: float = 80.0
    cpu_warning_pct: float = 80.0
    cpu_critical_pct: float = 90.0
    gpu_warning_pct: float = 80.0
    gpu_critical_pct: float = 90.0
    disk_warning_pct: float = 85.0
    disk_critical_pct: float = 95.0

    # 检查间隔
    check_interval_sec: float = 5.0

    # 自动保护
    auto_clean_cache: bool = True         # 内存>80% 清缓存
    auto_pause_non_critical: bool = True  # GPU>90% 暂停非关键任务
    auto_throttle: bool = True            # CPU>90% 降频


class ResourceManager:
    """通用资源管理器。

    功能:
      - 定期采集系统资源指标 (CPU/GPU/内存/磁盘)
      - 超过阈值自动执行保护动作
      - 通过 EventBus 推送资源告警
      - 为 /health 端点提供资源数据
    """

    def __init__(
        self,
        bus: EventBus | None = None,
        config: ResourceConfig | None = None,
        jetson_mode: bool = False,
    ) -> None:
        self._bus = bus
        self._config = config or ResourceConfig()
        self._jetson_mode = jetson_mode or bool(os.environ.get("STOCKSTREAM_JETSON_MODE"))

        self._running = False
        self._check_task: asyncio.Task | None = None
        self._current_snapshot: ResourceSnapshot = ResourceSnapshot()
        self._snapshot_history: list[ResourceSnapshot] = []  # 最近 100 个快照

        # 资源级别
        self._cpu_levels: list[ResourceLevel] = []
        self._mem_levels: list[ResourceLevel] = []
        self._gpu_levels: list[ResourceLevel] = []

        # 保护动作计数
        self._cache_clears: int = 0
        self._task_pauses: int = 0
        self._throttles: int = 0

        # 外部回调引用 (由 app.py 注入)
        self._on_clean_cache: callable | None = None
        self._on_pause_tasks: callable | None = None

        logger.info("ResourceManager initialized (jetson=%s)", self._jetson_mode)

    # ── Public API ─────────────────────────────────────────────────

    def set_callbacks(self, clean_cache: callable | None = None,
                      pause_tasks: callable | None = None) -> None:
        """注入保护动作回调。"""
        self._on_clean_cache = clean_cache
        self._on_pause_tasks = pause_tasks

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._check_task = asyncio.create_task(self._check_loop())
        logger.info("ResourceManager started (interval=%.1fs)",
                    self._config.check_interval_sec)

    async def stop(self) -> None:
        self._running = False
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
            self._check_task = None
        logger.info("ResourceManager stopped (clears=%d, pauses=%d, throttles=%d)",
                    self._cache_clears, self._task_pauses, self._throttles)

    def get_snapshot(self) -> ResourceSnapshot:
        return self._current_snapshot

    def get_summary(self) -> dict:
        snap = self._current_snapshot
        return {
            "cpu": {"percent": snap.cpu_percent, "level": self._assess_cpu().value},
            "memory": {
                "percent": snap.memory_percent,
                "used_gb": snap.memory_used_gb,
                "total_gb": snap.memory_total_gb,
                "level": self._assess_memory().value,
            },
            "gpu": {"percent": snap.gpu_percent, "memory_mb": snap.gpu_memory_mb,
                    "level": self._assess_gpu().value},
            "disk": {"percent": snap.disk_percent, "free_gb": snap.disk_free_gb},
            "protections": {"cache_clears": self._cache_clears,
                            "task_pauses": self._task_pauses,
                            "throttles": self._throttles},
        }

    # ── Check loop ─────────────────────────────────────────────────

    async def _check_loop(self) -> None:
        bus = await self._ensure_bus()
        while self._running:
            try:
                await self._run_check(bus)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("ResourceManager check error: %s", exc)
            await asyncio.sleep(self._config.check_interval_sec)

    async def _run_check(self, bus: EventBus) -> None:
        snap = self._collect_metrics()
        self._current_snapshot = snap

        # 保留最近 100 个快照 (约 8.3 分钟)
        self._snapshot_history.append(snap)
        if len(self._snapshot_history) > 100:
            self._snapshot_history = self._snapshot_history[-100:]

        # 评估级别
        cpu_level = self._assess_cpu()
        mem_level = self._assess_memory()
        gpu_level = self._assess_gpu()

        # 自动保护
        alerts: list[dict] = []
        if mem_level == ResourceLevel.CRITICAL:
            await self._protect_memory(bus)
            alerts.append({"resource": "memory", "level": "critical",
                           "value": snap.memory_percent})

        if gpu_level == ResourceLevel.CRITICAL:
            await self._protect_gpu(bus)
            alerts.append({"resource": "gpu", "level": "critical",
                           "value": snap.gpu_percent})

        if cpu_level == ResourceLevel.CRITICAL:
            await self._protect_cpu(bus)
            alerts.append({"resource": "cpu", "level": "critical",
                           "value": snap.cpu_percent})

        # 推送指标事件
        if alerts or (snap.timestamp - getattr(self, '_last_emit', 0) > 30):
            self._last_emit = snap.timestamp
            await bus.emit_async("resource.metrics", {
                "snapshot": {
                    "cpu": snap.cpu_percent,
                    "memory": snap.memory_percent,
                    "memory_used_gb": snap.memory_used_gb,
                    "gpu": snap.gpu_percent,
                    "disk": snap.disk_percent,
                },
                "alerts": alerts,
                "timestamp": snap.timestamp,
            })

        if alerts:
            await bus.emit_async("resource.alert", {
                "alerts": alerts,
                "timestamp": snap.timestamp,
            })

    # ── Metrics collection ─────────────────────────────────────────

    def _collect_metrics(self) -> ResourceSnapshot:
        snap = ResourceSnapshot()

        # CPU
        try:
            import psutil
            snap.cpu_percent = round(psutil.cpu_percent(interval=0.1), 1)
        except ImportError:
            snap.cpu_percent = 0.0

        # Memory
        try:
            import psutil
            mem = psutil.virtual_memory()
            snap.memory_percent = round(mem.percent, 1)
            snap.memory_used_gb = round(mem.used / (1024**3), 2)
            snap.memory_total_gb = round(mem.total / (1024**3), 2)
        except ImportError:
            snap.memory_percent = 0.0

        # Disk
        try:
            import psutil
            disk = psutil.disk_usage("/")
            snap.disk_percent = round(disk.percent, 1)
            snap.disk_free_gb = round(disk.free / (1024**3), 2)
        except ImportError:
            snap.disk_percent = 0.0

        # GPU (Jetson mode via tegrastats, otherwise via pynvml)
        if self._jetson_mode:
            try:
                from src.core.jetson_optimizer import get_gpu_stats
                gpu_stats = get_gpu_stats()
                snap.gpu_percent = gpu_stats.get("gpu_percent", 0.0)
                snap.gpu_memory_mb = gpu_stats.get("gpu_memory_mb", 0.0)
            except Exception:
                snap.gpu_percent = 0.0
                snap.gpu_memory_mb = 0.0

        return snap

    # ── Protection actions ─────────────────────────────────────────

    async def _protect_memory(self, bus: EventBus) -> None:
        if not self._config.auto_clean_cache:
            return
        self._cache_clears += 1
        logger.warning(
            "ResourceManager: memory %.1f%% > %.0f%%, clearing caches (#%d)",
            self._current_snapshot.memory_percent,
            self._config.memory_critical_pct,
            self._cache_clears,
        )
        # 通知缓存服务清空
        await bus.emit_async("resource.cache_clear", {"reason": "memory_pressure"})
        if self._on_clean_cache:
            try:
                self._on_clean_cache()
            except Exception as exc:
                logger.error("clean_cache callback error: %s", exc)

    async def _protect_gpu(self, bus: EventBus) -> None:
        if not self._config.auto_pause_non_critical:
            return
        self._task_pauses += 1
        logger.warning(
            "ResourceManager: GPU %.1f%% > %.0f%%, pausing non-critical tasks (#%d)",
            self._current_snapshot.gpu_percent,
            self._config.gpu_critical_pct,
            self._task_pauses,
        )
        await bus.emit_async("resource.pause_tasks", {"reason": "gpu_pressure"})
        if self._on_pause_tasks:
            try:
                self._on_pause_tasks()
            except Exception as exc:
                logger.error("pause_tasks callback error: %s", exc)

    async def _protect_cpu(self, bus: EventBus) -> None:
        if not self._config.auto_throttle:
            return
        self._throttles += 1
        logger.warning(
            "ResourceManager: CPU %.1f%% > %.0f%%, throttling (#%d)",
            self._current_snapshot.cpu_percent,
            self._config.cpu_critical_pct,
            self._throttles,
        )
        await bus.emit_async("resource.throttle", {"reason": "cpu_pressure"})

    # ── Level assessment ───────────────────────────────────────────

    def _assess_cpu(self) -> ResourceLevel:
        pct = self._current_snapshot.cpu_percent
        if pct >= self._config.cpu_critical_pct:
            return ResourceLevel.CRITICAL
        if pct >= self._config.cpu_warning_pct:
            return ResourceLevel.WARNING
        return ResourceLevel.NORMAL

    def _assess_memory(self) -> ResourceLevel:
        pct = self._current_snapshot.memory_percent
        if pct >= self._config.memory_critical_pct:
            return ResourceLevel.CRITICAL
        if pct >= self._config.memory_warning_pct:
            return ResourceLevel.WARNING
        return ResourceLevel.NORMAL

    def _assess_gpu(self) -> ResourceLevel:
        pct = self._current_snapshot.gpu_percent
        if pct >= self._config.gpu_critical_pct:
            return ResourceLevel.CRITICAL
        if pct >= self._config.gpu_warning_pct:
            return ResourceLevel.WARNING
        return ResourceLevel.NORMAL

    async def _ensure_bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus
