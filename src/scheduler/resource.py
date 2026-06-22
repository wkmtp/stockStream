"""Jetson 资源调度器 — 针对 Xavier NX 8GB 优化。

目标平台:
    - NVIDIA Jetson Xavier NX 8GB
    - 6-core Carmel ARM CPU
    - 384-core Volta GPU
    - 8GB LPDDR4x (共享 CPU+GPU)

控制策略:
    1. 内存超过 80% → 自动释放缓存
    2. GPU 超过 95% → 暂停非关键任务
    3. CPU 持续高负载 → 降频处理
    4. 温度过高 → 主动降温

用法:
    from src.scheduler.resource import ResourceScheduler

    rs = ResourceScheduler()
    rs.register_task("tts", priority=TaskPriority.HIGH)
    rs.register_task("clip", priority=TaskPriority.LOW)
    await rs.start()
"""

from __future__ import annotations

import asyncio
import gc
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine

from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


# ── Enums & Types ────────────────────────────────────────────────────────


class TaskPriority(Enum):
    CRITICAL = 0   # 推流、行情
    HIGH = 1        # TTS、分析
    NORMAL = 2      # 弹幕、运营
    LOW = 3         # 短视频、复盘
    BACKGROUND = 4  # 日志清理、缓存维护


class TaskState(Enum):
    RUNNING = "running"
    PAUSED = "paused"
    THROTTLED = "throttled"
    STOPPED = "stopped"


@dataclass
class TaskInfo:
    """任务信息。"""
    name: str
    priority: TaskPriority = TaskPriority.NORMAL
    state: TaskState = TaskState.RUNNING
    gpu_required: bool = False
    estimated_memory_mb: int = 100
    cpu_affinity: int = -1  # -1 = all cores
    last_run: float = field(default_factory=time.time)
    pause_callback: Callable[[], None] | None = None
    resume_callback: Callable[[], None] | None = None


@dataclass
class ResourceState:
    """当前资源状态。"""
    memory_percent: float = 0.0
    memory_used_gb: float = 0.0
    memory_total_gb: float = 8.0  # Jetson default
    cpu_percent: float = 0.0
    gpu_percent: float = 0.0
    gpu_mem_percent: float = 0.0
    temperature_c: float = 0.0
    swap_used_gb: float = 0.0
    timestamp: float = field(default_factory=time.time)


# ── Resource Scheduler ───────────────────────────────────────────────────


class ResourceScheduler:
    """Jetson 资源调度器。

    推送事件:
      resource.throttle      — 任务被限流
      resource.resume        — 任务恢复
      resource.emergency     — 紧急释放
      resource.state         — 资源状态快照
    """

    # 阈值 (针对 Jetson Xavier NX 8GB)
    MEM_WARN = 75.0         # 内存警告
    MEM_THROTTLE = 80.0     # 开始释放缓存
    MEM_CRITICAL = 90.0     # 紧急释放
    GPU_THROTTLE = 90.0     # GPU 限流
    GPU_CRITICAL = 95.0     # 暂停非关键 GPU 任务
    CPU_THROTTLE = 85.0     # CPU 限流
    TEMP_WARN = 80.0        # 温度警告 (°C)
    TEMP_CRITICAL = 90.0    # 温度临界

    def __init__(self, bus: EventBus | None = None,
                 check_interval: float = 2.0) -> None:
        self._bus: EventBus | None = bus
        self.check_interval = check_interval
        self._tasks: dict[str, TaskInfo] = {}
        self._running = False
        self._task: asyncio.Task | None = None
        self._state_history: list[ResourceState] = []
        self._max_history = 300
        self._paused_tasks: list[str] = []
        self._cache_release_count = 0
        self._throttle_count = 0

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    # ── Task Registration ───────────────────────────────────────────

    def register_task(
        self,
        name: str,
        priority: TaskPriority = TaskPriority.NORMAL,
        gpu_required: bool = False,
        estimated_memory_mb: int = 100,
        pause_callback: Callable[[], None] | None = None,
        resume_callback: Callable[[], None] | None = None,
    ) -> TaskInfo:
        """注册需要资源管理的任务。"""
        info = TaskInfo(
            name=name,
            priority=priority,
            gpu_required=gpu_required,
            estimated_memory_mb=estimated_memory_mb,
            pause_callback=pause_callback,
            resume_callback=resume_callback,
        )
        self._tasks[name] = info
        logger.debug("ResourceScheduler registered task: %s (priority=%s)", name, priority.value)
        return info

    # ── Lifecycle ───────────────────────────────────────────────────

    async def start(self) -> None:
        """启动资源调度器。"""
        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())

        bus = await self.bus
        @bus.on("resource.request_release")
        async def _on_request_release(event):
            await self._handle_release_request(event)

        logger.info("ResourceScheduler started (interval=%.1fs)", self.check_interval)

    async def stop(self) -> None:
        """停止资源调度器。"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # 恢复所有被暂停的任务
        await self._resume_all()
        logger.info("ResourceScheduler stopped")

    # ── Main Loop ───────────────────────────────────────────────────

    async def _scheduler_loop(self) -> None:
        """调度主循环。"""
        bus = await self.bus
        while self._running:
            try:
                state = await self._read_resource_state()
                self._state_history.append(state)
                if len(self._state_history) > self._max_history:
                    self._state_history = self._state_history[-self._max_history:]

                # 推送资源状态
                await bus.emit_async("resource.state", {
                    "memory_percent": state.memory_percent,
                    "gpu_percent": state.gpu_percent,
                    "cpu_percent": state.cpu_percent,
                    "temperature": state.temperature_c,
                })

                # 执行调度决策
                await self._evaluate_and_act(state)

                await asyncio.sleep(self.check_interval)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("ResourceScheduler loop error: %s", exc)
                await asyncio.sleep(5)

    async def _evaluate_and_act(self, state: ResourceState) -> None:
        """评估资源状态并执行相应操作。"""
        bus = await self.bus

        # ── 温度检查 (最高优先级) ──
        if state.temperature_c >= self.TEMP_CRITICAL:
            await self._emergency_cooldown(state)
            return

        if state.temperature_c >= self.TEMP_WARN:
            await self._thermal_throttle()

        # ── 内存检查 ──
        if state.memory_percent >= self.MEM_CRITICAL:
            await self._emergency_memory_release(state)
            return

        if state.memory_percent >= self.MEM_THROTTLE:
            await self._release_caches()

        if state.memory_percent >= self.MEM_WARN:
            await self._pause_low_priority("memory", state)

        # ── GPU 检查 ──
        if state.gpu_percent >= self.GPU_CRITICAL:
            await self._pause_gpu_tasks()
            await bus.emit_async("resource.emergency", {
                "reason": "gpu_critical",
                "gpu_percent": state.gpu_percent,
            })

        if state.gpu_percent >= self.GPU_THROTTLE:
            await self._throttle_gpu_tasks()

        # ── CPU 检查 ──
        if state.cpu_percent >= self.CPU_THROTTLE:
            await self._throttle_cpu_tasks()

        # ── 恢复检查 ──
        if (state.memory_percent < self.MEM_WARN - 5 and
            state.gpu_percent < self.GPU_THROTTLE - 10):
            await self._resume_if_possible()

    # ── Resource Reading ────────────────────────────────────────────

    async def _read_resource_state(self) -> ResourceState:
        """读取当前资源状态。"""
        state = ResourceState()

        try:
            import psutil
            # 内存
            mem = psutil.virtual_memory()
            state.memory_percent = mem.percent
            state.memory_used_gb = mem.used / (1024 ** 3)
            state.memory_total_gb = mem.total / (1024 ** 3)

            # Swap
            swap = psutil.swap_memory()
            state.swap_used_gb = swap.used / (1024 ** 3)

            # CPU
            state.cpu_percent = psutil.cpu_percent(interval=0.1)

            # 温度 (Jetson)
            state.temperature_c = await self._read_temperature()

            # GPU
            gpu_metrics = await self._read_gpu_metrics()
            state.gpu_percent = gpu_metrics.get("utilization", 0.0)
            state.gpu_mem_percent = gpu_metrics.get("mem_percent", 0.0)

        except ImportError:
            # 无 psutil 时使用系统文件
            state.temperature_c = await self._read_temperature()
            try:
                with open("/proc/meminfo") as f:
                    for line in f:
                        if "MemTotal" in line:
                            total_kb = int(line.split()[1])
                            state.memory_total_gb = total_kb / (1024 ** 2)
                        elif "MemAvailable" in line:
                            avail_kb = int(line.split()[1])
                            used_kb = state.memory_total_gb * 1024 * 1024 - avail_kb
                            state.memory_used_gb = used_kb / (1024 ** 2)
                            state.memory_percent = (used_kb / (state.memory_total_gb * 1024 * 1024)) * 100
                            break
            except (OSError, IOError):
                pass

        return state

    async def _read_temperature(self) -> float:
        """读取 CPU/GPU 温度。"""
        # Jetson 温度路径
        temp_paths = [
            "/sys/class/thermal/thermal_zone0/temp",
            "/sys/class/thermal/thermal_zone1/temp",
            "/sys/class/hwmon/hwmon0/temp1_input",
        ]
        for path in temp_paths:
            if os.path.exists(path):
                try:
                    with open(path) as f:
                        val = float(f.read().strip())
                        # m°C → °C
                        if val > 1000:
                            return val / 1000.0
                        return val
                except (OSError, ValueError):
                    continue
        return 0.0

    async def _read_gpu_metrics(self) -> dict[str, float]:
        """读取 GPU 指标。"""
        result: dict[str, float] = {}

        # Jetson GPU 负载
        gpu_load = "/sys/devices/gpu.0/load"
        if os.path.exists(gpu_load):
            try:
                with open(gpu_load) as f:
                    result["utilization"] = float(f.read().strip()) / 10.0
            except (OSError, ValueError):
                pass

        return result

    # ── Action Methods ──────────────────────────────────────────────

    async def _release_caches(self) -> None:
        """释放缓存。"""
        # Python GC
        gc.collect()

        # 系统缓存 (需要 root)
        self._cache_release_count += 1
        logger.info("ResourceScheduler: cache released (count=%d)", self._cache_release_count)

        bus = await self.bus
        await bus.emit_async("resource.cache_released", {
            "count": self._cache_release_count,
        })

    async def _emergency_memory_release(self, state: ResourceState) -> None:
        """紧急内存释放。"""
        logger.critical("ResourceScheduler: EMERGENCY memory release (%.1f%%)",
                       state.memory_percent)

        # 暂停所有低优先级任务
        await self._pause_low_priority("memory_critical", state)
        await self._release_caches()

        # 强制 GC
        gc.collect()
        gc.collect()  # double collect

        bus = await self.bus
        await bus.emit_async("resource.emergency", {
            "reason": "memory_critical",
            "memory_percent": state.memory_percent,
        })

    async def _emergency_cooldown(self, state: ResourceState) -> None:
        """紧急降温。"""
        logger.critical("ResourceScheduler: EMERGENCY cooldown (%.1f°C)",
                       state.temperature_c)

        # 暂停所有 GPU 任务
        await self._pause_gpu_tasks()
        await self._pause_low_priority("thermal", state)

        bus = await self.bus
        await bus.emit_async("resource.emergency", {
            "reason": "thermal_critical",
            "temperature": state.temperature_c,
        })

    async def _thermal_throttle(self) -> None:
        """温度限流。"""
        self._throttle_count += 1
        logger.warning("ResourceScheduler: thermal throttle (count=%d)", self._throttle_count)

        # 暂停低优先级 GPU 任务
        for name, info in list(self._tasks.items()):
            if info.gpu_required and info.priority.value >= TaskPriority.LOW.value:
                await self._pause_task(name)

    async def _pause_low_priority(self, reason: str, state: ResourceState) -> None:
        """暂停低优先级任务。"""
        bus = await self.bus
        for name, info in sorted(self._tasks.items(),
                                 key=lambda x: x[1].priority.value,
                                 reverse=True):
            if info.state != TaskState.RUNNING:
                continue

            # 只暂停 LOW 和 BACKGROUND
            if info.priority.value >= TaskPriority.LOW.value:
                await self._pause_task(name)
                await bus.emit_async("resource.throttle", {
                    "task": name,
                    "reason": reason,
                    "priority": info.priority.value,
                })

    async def _pause_gpu_tasks(self) -> None:
        """暂停所有 GPU 任务。"""
        for name, info in self._tasks.items():
            if info.gpu_required and info.state == TaskState.RUNNING:
                await self._pause_task(name)

    async def _throttle_gpu_tasks(self) -> None:
        """GPU 任务限流。"""
        for name, info in self._tasks.items():
            if (info.gpu_required and
                info.priority.value >= TaskPriority.LOW.value and
                info.state == TaskState.RUNNING):
                await self._pause_task(name)

    async def _throttle_cpu_tasks(self) -> None:
        """CPU 任务限流。"""
        for name, info in self._tasks.items():
            if info.priority.value >= TaskPriority.BACKGROUND.value and \
               info.state == TaskState.RUNNING:
                await self._pause_task(name)

    async def _pause_task(self, name: str) -> None:
        """暂停单个任务。"""
        if name not in self._tasks:
            return
        info = self._tasks[name]
        if info.state != TaskState.RUNNING:
            return

        info.state = TaskState.PAUSED
        self._paused_tasks.append(name)

        if info.pause_callback:
            try:
                info.pause_callback()
            except Exception as exc:
                logger.error("Pause callback for %s failed: %s", name, exc)

        logger.info("ResourceScheduler: paused task %s", name)

    async def _resume_task(self, name: str) -> None:
        """恢复单个任务。"""
        if name not in self._tasks:
            return
        info = self._tasks[name]
        if info.state != TaskState.PAUSED:
            return

        info.state = TaskState.RUNNING
        if name in self._paused_tasks:
            self._paused_tasks.remove(name)

        if info.resume_callback:
            try:
                info.resume_callback()
            except Exception as exc:
                logger.error("Resume callback for %s failed: %s", name, exc)

        bus = await self.bus
        await bus.emit_async("resource.resume", {"task": name})
        logger.info("ResourceScheduler: resumed task %s", name)

    async def _resume_if_possible(self) -> None:
        """尝试恢复被暂停的任务。"""
        # 按优先级从高到低恢复
        for name in sorted(self._paused_tasks,
                           key=lambda n: self._tasks[n].priority.value):
            info = self._tasks[name]
            if info.state == TaskState.PAUSED:
                await self._resume_task(name)

    async def _resume_all(self) -> None:
        """恢复所有被暂停的任务。"""
        for name in list(self._paused_tasks):
            await self._resume_task(name)

    async def _handle_release_request(self, event: Any) -> None:
        """处理外部释放请求。"""
        data = event.data or {}
        requested_mb = data.get("memory_mb", 0)

        if requested_mb > 0:
            logger.info("ResourceScheduler: external release request (%d MB)", requested_mb)
            await self._release_caches()

    # ── Query ───────────────────────────────────────────────────────

    def get_state(self) -> dict[str, Any]:
        """获取当前资源状态。"""
        if self._state_history:
            state = self._state_history[-1]
            return {
                "memory_percent": state.memory_percent,
                "memory_used_gb": state.memory_used_gb,
                "memory_total_gb": state.memory_total_gb,
                "cpu_percent": state.cpu_percent,
                "gpu_percent": state.gpu_percent,
                "temperature_c": state.temperature_c,
                "paused_tasks": len(self._paused_tasks),
                "cache_releases": self._cache_release_count,
                "throttle_count": self._throttle_count,
            }
        return {}

    def get_tasks(self) -> dict[str, dict]:
        """获取所有任务状态。"""
        return {
            name: {
                "priority": info.priority.value,
                "state": info.state.value,
                "gpu_required": info.gpu_required,
                "estimated_memory_mb": info.estimated_memory_mb,
            }
            for name, info in self._tasks.items()
        }

    def get_stats(self) -> dict[str, Any]:
        return {
            "tasks_total": len(self._tasks),
            "tasks_paused": len(self._paused_tasks),
            "cache_releases": self._cache_release_count,
            "throttle_count": self._throttle_count,
            "state": self.get_state(),
        }
