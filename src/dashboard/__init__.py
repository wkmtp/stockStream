"""数据驾驶舱模块。

职责:
  - 实时数据聚合
  - 仪表盘渲染

依赖: core (EventBus), market, live
被依赖: agents, monitoring
"""

from src.dashboard.service import DashboardService

__all__ = ["DashboardService"]
