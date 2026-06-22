"""监控中心 — 全维度系统监控 + Web 仪表盘。

特性:
    1. 系统资源: CPU / GPU / 内存 / 磁盘 / 网络
    2. 业务状态: 推流 / 直播 / 数据库 / 模块健康
    3. Web 监控页面: 实时仪表盘
    4. 告警: 阈值告警 + 事件通知
    5. 历史趋势: 资源使用历史

用法:
    from src.monitoring.center import MonitoringCenter

    mc = MonitoringCenter()
    await mc.start()
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import shutil
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


# ── Data Types ───────────────────────────────────────────────────────────


@dataclass
class SystemMetrics:
    """系统资源指标。"""
    cpu_percent: float = 0.0
    cpu_count: int = 0
    memory_total_gb: float = 0.0
    memory_used_gb: float = 0.0
    memory_percent: float = 0.0
    disk_total_gb: float = 0.0
    disk_used_gb: float = 0.0
    disk_percent: float = 0.0
    gpu_available: bool = False
    gpu_percent: float = 0.0
    gpu_memory_used_gb: float = 0.0
    gpu_memory_total_gb: float = 0.0
    gpu_temperature: float = 0.0
    net_bytes_sent: int = 0
    net_bytes_recv: int = 0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cpu_percent": round(self.cpu_percent, 1),
            "cpu_count": self.cpu_count,
            "memory_total_gb": round(self.memory_total_gb, 1),
            "memory_used_gb": round(self.memory_used_gb, 1),
            "memory_percent": round(self.memory_percent, 1),
            "disk_total_gb": round(self.disk_total_gb, 1),
            "disk_used_gb": round(self.disk_used_gb, 1),
            "disk_percent": round(self.disk_percent, 1),
            "gpu_available": self.gpu_available,
            "gpu_percent": round(self.gpu_percent, 1),
            "gpu_memory_used_gb": round(self.gpu_memory_used_gb, 2),
            "gpu_memory_total_gb": round(self.gpu_memory_total_gb, 2),
            "gpu_temperature": round(self.gpu_temperature, 1),
            "net_bytes_sent": self.net_bytes_sent,
            "net_bytes_recv": self.net_bytes_recv,
            "timestamp": self.timestamp,
        }


@dataclass
class AlertRule:
    """告警规则。"""
    name: str
    metric: str
    operator: str  # > / < / >= / <= / ==
    threshold: float
    severity: str = "warning"  # info / warning / critical
    cooldown_seconds: float = 60.0
    last_triggered: float = 0.0

    def check(self, value: float) -> bool:
        """检查是否触发告警。"""
        ops = {
            ">": lambda a, b: a > b,
            "<": lambda a, b: a < b,
            ">=": lambda a, b: a >= b,
            "<=": lambda a, b: a <= b,
            "==": lambda a, b: a == b,
        }
        return ops.get(self.operator, lambda a, b: False)(value, self.threshold)


@dataclass
class Alert:
    """告警记录。"""
    rule_name: str
    metric: str
    current_value: float
    threshold: float
    severity: str
    message: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_name": self.rule_name,
            "metric": self.metric,
            "current_value": self.current_value,
            "threshold": self.threshold,
            "severity": self.severity,
            "message": self.message,
            "timestamp": self.timestamp,
        }


# ── Monitoring Center ───────────────────────────────────────────────────


class MonitoringCenter:
    """监控中心 — 全维度系统监控。

    推送事件:
      monitoring.metrics     — 系统指标快照
      monitoring.alert       — 告警事件
      monitoring.status      — 整体状态
    """

    # GPU 检测阈值
    GPU_MEM_WARN = 85.0
    GPU_MEM_CRIT = 95.0
    MEM_WARN = 80.0
    MEM_CRIT = 90.0
    DISK_WARN = 85.0
    DISK_CRIT = 95.0
    CPU_WARN = 80.0
    CPU_CRIT = 95.0

    def __init__(
        self,
        bus: EventBus | None = None,
        interval: float = 5.0,
        history_size: int = 720,  # 1 hour at 5s
    ) -> None:
        self._bus: EventBus | None = bus
        self.interval = interval
        self._running = False
        self._task: asyncio.Task | None = None
        self._history: list[SystemMetrics] = []
        self._max_history = history_size
        self._alerts: list[Alert] = []
        self._max_alerts = 500
        self._alert_rules: list[AlertRule] = []
        self._started_at = time.time()

        # 业务健康检查
        self._health_checks: dict[str, Callable[[], Coroutine[Any, Any, tuple[bool, str]]]] = {}

        # 初始化默认告警规则
        self._init_default_rules()

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    # ── Lifecycle ───────────────────────────────────────────────────

    async def start(self) -> None:
        """启动监控中心。"""
        self._running = True
        self._task = asyncio.create_task(self._collect_loop())
        logger.info("MonitoringCenter started (interval=%.1fs)", self.interval)

    async def stop(self) -> None:
        """停止监控中心。"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("MonitoringCenter stopped")

    # ── Collection ──────────────────────────────────────────────────

    async def _collect_loop(self) -> None:
        """采集循环。"""
        bus = await self.bus
        while self._running:
            try:
                metrics = await self.collect_metrics()
                self._history.append(metrics)
                if len(self._history) > self._max_history:
                    self._history = self._history[-self._max_history:]

                # 推送指标
                await bus.emit_async("monitoring.metrics", metrics.to_dict())

                # 检查告警
                await self._check_alerts(metrics)

                # 业务健康检查
                await self._run_health_checks()

                await asyncio.sleep(self.interval)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("MonitoringCenter collect error: %s", exc)
                await asyncio.sleep(5)

    async def collect_metrics(self) -> SystemMetrics:
        """采集一次系统指标。"""
        metrics = SystemMetrics()

        if HAS_PSUTIL:
            # CPU
            metrics.cpu_percent = psutil.cpu_percent(interval=0.5)
            metrics.cpu_count = psutil.cpu_count()

            # 内存
            mem = psutil.virtual_memory()
            metrics.memory_total_gb = mem.total / (1024 ** 3)
            metrics.memory_used_gb = mem.used / (1024 ** 3)
            metrics.memory_percent = mem.percent

            # 磁盘
            disk = psutil.disk_usage("/")
            metrics.disk_total_gb = disk.total / (1024 ** 3)
            metrics.disk_used_gb = disk.used / (1024 ** 3)
            metrics.disk_percent = disk.percent

            # 网络
            net = psutil.net_io_counters()
            metrics.net_bytes_sent = net.bytes_sent
            metrics.net_bytes_recv = net.bytes_recv

        else:
            # fallback: os-level
            try:
                import resource
                mem_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                metrics.memory_used_gb = mem_bytes / (1024 ** 2) / 1024
            except ImportError:
                pass

        # GPU (Jetson / NVIDIA)
        metrics.gpu_available = self._check_gpu_available()
        if metrics.gpu_available:
            gpu_metrics = await self._collect_gpu_metrics()
            metrics.gpu_percent = gpu_metrics.get("utilization", 0.0)
            metrics.gpu_memory_used_gb = gpu_metrics.get("mem_used_gb", 0.0)
            metrics.gpu_memory_total_gb = gpu_metrics.get("mem_total_gb", 0.0)
            metrics.gpu_temperature = gpu_metrics.get("temperature", 0.0)

        return metrics

    def _check_gpu_available(self) -> bool:
        """检测 GPU 是否可用。"""
        # 检查 nvidia-smi
        if shutil.which("nvidia-smi"):
            return True
        # Jetson: 检查 tegrastats
        if shutil.which("tegrastats"):
            return True
        # 检查 /sys/class/thermal (Jetson)
        if os.path.exists("/sys/devices/gpu.0/load"):
            return True
        return False

    async def _collect_gpu_metrics(self) -> dict[str, float]:
        """采集 GPU 指标。"""
        result: dict[str, float] = {}

        try:
            # NVIDIA GPU via nvidia-smi
            if shutil.which("nvidia-smi"):
                proc = await asyncio.create_subprocess_exec(
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                    "--format=csv,noheader,nounits",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                line = stdout.decode().strip()
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 4:
                    result["utilization"] = float(parts[0])
                    result["mem_used_gb"] = float(parts[1]) / 1024.0
                    result["mem_total_gb"] = float(parts[2]) / 1024.0
                    result["temperature"] = float(parts[3])
                return result

            # Jetson: 通过 sysfs
            gpu_load_path = "/sys/devices/gpu.0/load"
            if os.path.exists(gpu_load_path):
                with open(gpu_load_path) as f:
                    result["utilization"] = float(f.read().strip()) / 10.0

            # Jetson 温度
            for zone in ["/sys/class/thermal/thermal_zone0/temp",
                         "/sys/class/thermal/thermal_zone1/temp"]:
                if os.path.exists(zone):
                    with open(zone) as f:
                        result["temperature"] = float(f.read().strip()) / 1000.0
                    break

            # Jetson 内存（tegrastats）
            if shutil.which("tegrastats"):
                proc = await asyncio.create_subprocess_exec(
                    "tegrastats", "--interval", "1000", "--count", "1",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(
                    proc.communicate(), timeout=3.0,
                )
                output = stdout.decode()
                # Parse RAM usage
                if "RAM" in output:
                    ram_part = output.split("RAM")[1].split("/")
                    if len(ram_part) >= 2:
                        try:
                            used = int(ram_part[0].strip())
                            total = int(ram_part[1].split("(")[0].strip())
                            result.setdefault("mem_used_gb", used / 1024.0)
                            result.setdefault("mem_total_gb", total / 1024.0)
                        except (ValueError, IndexError):
                            pass

        except (OSError, ValueError, asyncio.TimeoutError) as exc:
            logger.debug("GPU metrics collection skipped: %s", exc)

        return result

    # ── Alert Rules ─────────────────────────────────────────────────

    def _init_default_rules(self) -> None:
        """初始化默认告警规则。"""
        self._alert_rules = [
            AlertRule("cpu_critical", "cpu_percent", ">", self.CPU_CRIT, "critical", 60),
            AlertRule("cpu_warning", "cpu_percent", ">", self.CPU_WARN, "warning", 120),
            AlertRule("memory_critical", "memory_percent", ">", self.MEM_CRIT, "critical", 60),
            AlertRule("memory_warning", "memory_percent", ">", self.MEM_WARN, "warning", 120),
            AlertRule("disk_critical", "disk_percent", ">", self.DISK_CRIT, "critical", 300),
            AlertRule("disk_warning", "disk_percent", ">", self.DISK_WARN, "warning", 600),
            AlertRule("gpu_memory_critical", "gpu_percent", ">", self.GPU_MEM_CRIT, "critical", 60),
            AlertRule("gpu_memory_warning", "gpu_percent", ">", self.GPU_MEM_WARN, "warning", 120),
        ]

    def add_alert_rule(self, rule: AlertRule) -> None:
        """添加自定义告警规则。"""
        self._alert_rules.append(rule)

    async def _check_alerts(self, metrics: SystemMetrics) -> None:
        """检查所有告警规则。"""
        bus = await self.bus
        metric_dict = metrics.to_dict()
        now = time.time()

        for rule in self._alert_rules:
            value = metric_dict.get(rule.metric, 0.0)
            if rule.check(value) and (now - rule.last_triggered) > rule.cooldown_seconds:
                rule.last_triggered = now
                alert = Alert(
                    rule_name=rule.name,
                    metric=rule.metric,
                    current_value=value,
                    threshold=rule.threshold,
                    severity=rule.severity,
                    message=f"{rule.metric} = {value} {rule.operator} {rule.threshold}",
                )
                self._alerts.append(alert)
                if len(self._alerts) > self._max_alerts:
                    self._alerts = self._alerts[-self._max_alerts:]

                logger.warning("ALERT [%s]: %s", rule.severity, alert.message)

                await bus.emit_async("monitoring.alert", {
                    "module": "system",
                    "severity": rule.severity,
                    "metric": rule.metric,
                    "value": value,
                    "threshold": rule.threshold,
                    "message": alert.message,
                })

    # ── Health Checks ───────────────────────────────────────────────

    def register_health_check(
        self,
        name: str,
        check_fn: Callable[[], Coroutine[Any, Any, tuple[bool, str]]],
    ) -> None:
        """注册业务健康检查。"""
        self._health_checks[name] = check_fn

    async def _run_health_checks(self) -> None:
        """执行所有业务健康检查。"""
        bus = await self.bus
        for name, check_fn in self._health_checks.items():
            try:
                healthy, msg = await check_fn()
                if not healthy:
                    await bus.emit_async("monitoring.alert", {
                        "module": name,
                        "message": msg,
                        "severity": "warning",
                    })
            except Exception as exc:
                await bus.emit_async("monitoring.alert", {
                    "module": name,
                    "message": f"health check error: {exc}",
                    "severity": "error",
                })

    # ── Query ───────────────────────────────────────────────────────

    def latest_metrics(self) -> dict[str, Any]:
        """获取最新系统指标。"""
        if self._history:
            return self._history[-1].to_dict()
        return {}

    def get_history(self, limit: int = 60) -> list[dict[str, Any]]:
        """获取历史指标。"""
        return [m.to_dict() for m in self._history[-limit:]]

    def get_alerts(self, severity: str = "", limit: int = 50) -> list[dict[str, Any]]:
        """获取告警记录。"""
        alerts = self._alerts
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        return [a.to_dict() for a in alerts[-limit:]]

    def get_status(self) -> dict[str, Any]:
        """获取系统整体状态。"""
        metrics = self.latest_metrics()
        status = "healthy"

        # 检查关键指标
        if metrics.get("memory_percent", 0) > self.MEM_CRIT:
            status = "critical"
        elif metrics.get("memory_percent", 0) > self.MEM_WARN:
            status = "warning"
        elif metrics.get("cpu_percent", 0) > self.CPU_CRIT:
            status = "critical"

        return {
            "status": status,
            "uptime_seconds": time.time() - self._started_at,
            "system": platform.system(),
            "python_version": platform.python_version(),
            "psutil_available": HAS_PSUTIL,
            "gpu_available": metrics.get("gpu_available", False),
            "metrics": metrics,
            "alert_count": len(self._alerts),
            "health_checks": len(self._health_checks),
        }

    def uptime_seconds(self) -> float:
        return time.time() - self._started_at

    # ── Web Dashboard Data ──────────────────────────────────────────

    def dashboard_data(self) -> dict[str, Any]:
        """生成 Web 监控页面所需的数据。"""
        metrics = self.latest_metrics()
        return {
            "status": self.get_status(),
            "metrics": metrics,
            "history": self.get_history(limit=120),
            "recent_alerts": self.get_alerts(limit=20),
            "resources": {
                "cpu": {
                    "percent": metrics.get("cpu_percent", 0),
                    "count": metrics.get("cpu_count", 0),
                },
                "memory": {
                    "percent": metrics.get("memory_percent", 0),
                    "total_gb": metrics.get("memory_total_gb", 0),
                    "used_gb": metrics.get("memory_used_gb", 0),
                },
                "disk": {
                    "percent": metrics.get("disk_percent", 0),
                    "total_gb": metrics.get("disk_total_gb", 0),
                    "used_gb": metrics.get("disk_used_gb", 0),
                },
                "gpu": {
                    "available": metrics.get("gpu_available", False),
                    "percent": metrics.get("gpu_percent", 0),
                    "memory_used_gb": metrics.get("gpu_memory_used_gb", 0),
                    "memory_total_gb": metrics.get("gpu_memory_total_gb", 0),
                    "temperature": metrics.get("gpu_temperature", 0),
                },
            },
        }
