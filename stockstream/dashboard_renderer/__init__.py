"""dashboard_renderer — 全屏财经数据大屏模块。

实时显示：
    上证指数、深证指数、创业板、北向资金
    涨停数、跌停数、涨跌家数、热点板块、资金流向

每10秒自动刷新，生成1920x1080全屏PNG供数字人直播切换。
"""

from stockstream.dashboard_renderer.models import (
    DashboardConfig,
    DashboardData,
    DashboardResult,
    IndexData,
    NorthboundFlow,
    LimitStats,
    AdvanceDeclineStats,
    HotSector,
    FundFlowSummary,
)
from stockstream.dashboard_renderer.engine import (
    DashboardEngine,
    create_dashboard_engine,
)

__all__ = [
    "DashboardConfig",
    "DashboardData",
    "DashboardResult",
    "IndexData",
    "NorthboundFlow",
    "LimitStats",
    "AdvanceDeclineStats",
    "HotSector",
    "FundFlowSummary",
    "DashboardEngine",
    "create_dashboard_engine",
]
