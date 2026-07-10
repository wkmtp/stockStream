"""Metrics collector: gather system & application metrics.

Collects:
  - CPU usage (per-core and total)
  - GPU usage (CUDA/Jetson)
  - RAM usage (total/available/percent)
  - Disk I/O and usage
  - Network bandwidth
  - WebSocket connection count
  - Inference queue depth
  - ONNX session stats
  - Database pool stats
  - Python GC stats

Compatible: Python 3.8+ (no zoneinfo, no match-case)
"""
from __future__ import annotations

import os
import time
import threading
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from collections import deque

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

logger = logging.getLogger(__name__)


@dataclass
class CPUMetrics:
    """CPU usage snapshot."""
    percent: float = 0.0
    per_core: List[float] = field(default_factory=list)
    count: int = 0
    freq_current: float = 0.0


@dataclass
class MemoryMetrics:
    """RAM usage snapshot."""
    total_mb: float = 0.0
    available_mb: float = 0.0
    used_mb: float = 0.0
    percent: float = 0.0
    swap_total_mb: float = 0.0
    swap_used_mb: float = 0.0


@dataclass
class GPUMetrics:
    """GPU usage snapshot (NVIDIA/Jetson)."""
    available: bool = False
    name: str = ""
    temperature: float = 0.0
    memory_total_mb: float = 0.0
    memory_used_mb: float = 0.0
    memory_percent: float = 0.0
    utilization_percent: float = 0.0
    cuda_version: str = ""
    tensorrt_version: str = ""


@dataclass
class DiskMetrics:
    """Disk I/O and usage snapshot."""
    total_gb: float = 0.0
    used_gb: float = 0.0
    free_gb: float = 0.0
    percent: float = 0.0
    read_bytes: float = 0.0
    write_bytes: float = 0.0


@dataclass
class AppMetrics:
    """Application-level metrics."""
    websocket_connections: int = 0
    inference_queue_depth: int = 0
    db_pool_size: int = 0
    db_pool_active: int = 0
    active_streams: int = 0
    fps: float = 0.0
    frame_latency_ms: float = 0.0
    tts_latency_ms: float = 0.0
    subtitle_latency_ms: float = 0.0
    uptime_seconds: float = 0.0
    python_gc_count: int = 0
    errors_24h: int = 0
    restarts_24h: int = 0


class MetricsCollector:
    """Unified metrics collector with thread-safe history."""

    HISTORY_SIZE = 3600  # 1 hour at 1 sample/sec

    def __init__(self) -> None:
        self._start_time = time.time()
        self._lock = threading.Lock()
        self._history: deque = deque(maxlen=self.HISTORY_SIZE)
        self._sample_interval = 1.0
        self._last_sample_time = 0.0
        self._error_count = 0
        self._restart_count = 0

        # Application metrics (set by other modules)
        self.ws_connections = 0
        self.inference_queue = 0
        self.db_pool_size = 0
        self.db_pool_active = 0
        self.active_streams = 0
        self.current_fps = 0.0
        self.frame_latency = 0.0
        self.tts_latency = 0.0
        self.subtitle_latency = 0.0

    # ── CPU ──

    def collect_cpu(self) -> CPUMetrics:
        """Collect CPU metrics."""
        m = CPUMetrics()
        if HAS_PSUTIL:
            m.percent = psutil.cpu_percent(interval=0.1)
            m.per_core = psutil.cpu_percent(interval=0.1, percpu=True)  # type: ignore[assignment]
            m.count = psutil.cpu_count(logical=True) or 0
            freq = psutil.cpu_freq()
            if freq:
                m.freq_current = freq.current
        return m

    # ── Memory ──

    def collect_memory(self) -> MemoryMetrics:
        """Collect memory metrics."""
        m = MemoryMetrics()
        if HAS_PSUTIL:
            mem = psutil.virtual_memory()
            m.total_mb = mem.total / (1024 * 1024)
            m.available_mb = mem.available / (1024 * 1024)
            m.used_mb = mem.used / (1024 * 1024)
            m.percent = mem.percent
            swap = psutil.swap_memory()
            m.swap_total_mb = swap.total / (1024 * 1024)
            m.swap_used_mb = swap.used / (1024 * 1024)
        return m

    # ── GPU ──

    def collect_gpu(self) -> GPUMetrics:
        """Collect GPU metrics (NVIDIA SMI / Jetson tegrastats)."""
        m = GPUMetrics()
        try:
            # Try pynvml (NVIDIA Management Library)
            import pynvml
            pynvml.nvmlInit()
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            m.available = True
            m.name = pynvml.nvmlDeviceGetName(handle)  # type: ignore[assignment]
            m.temperature = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            m.memory_total_mb = mem_info.total / (1024 * 1024)
            m.memory_used_mb = mem_info.used / (1024 * 1024)
            m.memory_percent = (mem_info.used / mem_info.total) * 100
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            m.utilization_percent = util.gpu
            m.cuda_version = str(pynvml.nvmlSystemGetCudaDriverVersion())
        except Exception:
            # Fallback: try jetson-stats
            try:
                import jtop
                with jtop.jtop() as jetson:
                    stats = jetson.stats
                    if stats:
                        m.available = True
                        m.temperature = stats.get("Temp GPU", 0)
                        m.memory_used_mb = stats.get("RAM", 0) - stats.get("RAM free", 0)
                        m.memory_total_mb = stats.get("RAM", 0)
                        m.memory_percent = (m.memory_used_mb / max(m.memory_total_mb, 1)) * 100
                        m.utilization_percent = stats.get("GPU", 0)
            except Exception:
                pass
        return m

    # ── Disk ──

    def collect_disk(self, path: str = "/") -> DiskMetrics:
        """Collect disk metrics."""
        m = DiskMetrics()
        if HAS_PSUTIL:
            usage = psutil.disk_usage(path)
            m.total_gb = usage.total / (1024**3)
            m.used_gb = usage.used / (1024**3)
            m.free_gb = usage.free / (1024**3)
            m.percent = usage.percent
            io_ctrs = psutil.disk_io_counters()
            if io_ctrs:
                m.read_bytes = io_ctrs.read_bytes
                m.write_bytes = io_ctrs.write_bytes
        return m

    # ── Application ──

    def collect_app(self) -> AppMetrics:
        """Collect application-level metrics."""
        import gc
        return AppMetrics(
            websocket_connections=self.ws_connections,
            inference_queue_depth=self.inference_queue,
            db_pool_size=self.db_pool_size,
            db_pool_active=self.db_pool_active,
            active_streams=self.active_streams,
            fps=self.current_fps,
            frame_latency_ms=self.frame_latency,
            tts_latency_ms=self.tts_latency,
            subtitle_latency_ms=self.subtitle_latency,
            uptime_seconds=time.time() - self._start_time,
            python_gc_count=gc.get_count()[0],
            errors_24h=self._error_count,
            restarts_24h=self._restart_count,
        )

    # ── Full Snapshot ──

    def collect_all(self) -> Dict[str, Any]:
        """Collect full metrics snapshot."""
        now = time.time()
        if now - self._last_sample_time < self._sample_interval:
            if self._history:
                return self._history[-1]

        snapshot = {
            "timestamp": now,
            "cpu": self.collect_cpu(),
            "memory": self.collect_memory(),
            "gpu": self.collect_gpu(),
            "disk": self.collect_disk(),
            "app": self.collect_app(),
        }
        with self._lock:
            self._history.append(snapshot)
            self._last_sample_time = now
        return snapshot

    def get_history(self, count: int = 60) -> List[Dict[str, Any]]:
        """Get recent metrics history."""
        with self._lock:
            items = list(self._history)
            return items[-count:] if count < len(items) else items

    def increment_errors(self) -> None:
        """Track error count."""
        self._error_count += 1

    def increment_restarts(self) -> None:
        """Track restart count."""
        self._restart_count += 1

    @property
    def uptime_seconds(self) -> float:
        """System uptime in seconds."""
        return time.time() - self._start_time
