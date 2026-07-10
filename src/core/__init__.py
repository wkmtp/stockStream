"""核心基础设施层。

本层为整个项目提供基础能力：
  - ConfigCenter: 统一配置管理
  - EventBus: 发布/订阅事件总线
  - 基础类型和异常
"""

from src.core.config_center import ConfigCenter
from src.core.event_bus import EventBus, Event, EventCategory, get_event_bus
from src.core.base import (
    ModuleStatus,
    ModuleInfo,
    OperationResult,
    HealthStatus,
    StockStreamError,
    ModuleInitError,
    ModuleHealthError,
    ConfigError,
    DatabaseError,
    MarketError,
    StreamError,
    utc_now,
    ts_now,
)

__all__ = [
    "ConfigCenter",
    "EventBus",
    "Event",
    "EventCategory",
    "get_event_bus",
    "ModuleStatus",
    "ModuleInfo",
    "OperationResult",
    "HealthStatus",
    "StockStreamError",
    "ModuleInitError",
    "ModuleHealthError",
    "ConfigError",
    "DatabaseError",
    "MarketError",
    "StreamError",
    "utc_now",
    "ts_now",
]
