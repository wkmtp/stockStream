"""自动交易模块。

职责:
  - 模拟/实盘交易执行
  - 投资组合管理

依赖: core (EventBus), market, selector
被依赖: agents
"""

from src.trading.service import TradingService
from src.trading.models import Portfolio, Position, Transaction

__all__ = ["TradingService", "Portfolio", "Position", "Transaction"]
