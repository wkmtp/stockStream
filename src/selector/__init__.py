"""选股策略模块。

职责:
  - 基于技术指标筛选候选股票
  - 通过事件总线发布选股结果

依赖: core (EventBus), market
被依赖: agents, trading
"""

from src.selector.service import SelectorService
from src.selector.models import SelectorResult, SignalCandidate

__all__ = ["SelectorService", "SelectorResult", "SignalCandidate"]
