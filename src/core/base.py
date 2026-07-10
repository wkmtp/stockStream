"""核心基础设施 — 基础类型和异常定义。

此模块不依赖任何其他 src 子模块，作为整个项目的类型基础设施。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# ── Exceptions ─────────────────────────────────────────────────────────


class StockStreamError(Exception):
    """StockStream 基础异常。"""


class ModuleInitError(StockStreamError):
    """模块初始化失败。"""


class ModuleHealthError(StockStreamError):
    """模块健康检查失败。"""


class ConfigError(StockStreamError):
    """配置错误。"""


class DatabaseError(StockStreamError):
    """数据库错误。"""


class MarketError(StockStreamError):
    """行情数据错误。"""


class StreamError(StockStreamError):
    """推流错误。"""


# ── Module Interface ───────────────────────────────────────────────────


class ModuleStatus(Enum):
    """模块运行状态。"""
    UNINITIALIZED = "uninitialized"
    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class ModuleInfo:
    """模块元信息。"""
    name: str
    version: str = "1.0.0"
    status: ModuleStatus = ModuleStatus.UNINITIALIZED
    started_at: datetime | None = None
    dependencies: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Result Types ───────────────────────────────────────────────────────


@dataclass
class OperationResult:
    """通用操作结果。"""
    success: bool
    message: str = ""
    data: Any = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "error": self.error,
            "data": str(self.data) if self.data else None,
        }


@dataclass
class HealthStatus:
    """健康检查结果。"""
    healthy: bool
    module: str
    status: ModuleStatus = ModuleStatus.RUNNING
    uptime_seconds: float = 0.0
    message: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "module": self.module,
            "status": self.status.value,
            "uptime_seconds": round(self.uptime_seconds, 1),
            "message": self.message,
            "metrics": self.metrics,
        }


# ── Time helpers ───────────────────────────────────────────────────────


def utc_now() -> datetime:
    """返回当前 UTC 时间。"""
    return datetime.now(timezone.utc)


def ts_now() -> str:
    """返回当前 UTC ISO 时间字符串。"""
    return utc_now().isoformat()
