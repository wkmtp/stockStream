"""AI Agent 集合。

职责:
  - Chief Director Agent (总导演)
  - Stock QA Agent (股票问答)
  - 各类 AI 决策 Agent

依赖: core (EventBus), analysis, live, market, tts
被依赖: 无（顶层编排模块）
"""

from src.agents.chief_director import ChiefDirector
from src.agents.stock_qa import StockQAAgent

__all__ = ["ChiefDirector", "StockQAAgent"]
