"""AI 分析模块。

职责:
  - 调用 DeepSeek LLM 生成股票分析
  - 通过事件总线发布分析结果

依赖: core (EventBus, ConfigCenter), market
被依赖: tts, agents
"""

from src.analysis.service import AnalysisService
from src.analysis.models import AnalysisResult

__all__ = ["AnalysisService", "AnalysisResult"]
