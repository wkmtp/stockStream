"""行情数据模块。

职责:
  - 通过 AkShare/Tushare 采集实时行情
  - 缓存到本地 SQLite
  - 通过事件总线发布行情更新

依赖: core (EventBus, ConfigCenter), storage
被依赖: analysis, selector, agents
"""

from src.market.service import MarketService
from src.market.collector import MarketCollector
from src.market.models import MarketSnapshot

__all__ = ["MarketService", "MarketCollector", "MarketSnapshot"]
