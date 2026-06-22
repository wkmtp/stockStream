"""AI 分析服务 — 通过事件总线通讯。"""
from __future__ import annotations
import logging
from src.core.event_bus import EventBus, get_event_bus
from src.analysis.models import AnalysisResult, StockQA
from src.core.config_center import ConfigCenter

logger = logging.getLogger(__name__)


class AnalysisService:
    """AI 分析服务。

    推送事件:
      analysis.complete    — 分析完成
      analysis.qa_answer   — 问答回复
    """

    def __init__(self, bus: EventBus | None = None) -> None:
        self._bus: EventBus | None = bus
        self._api_key = ""
        self._model = "deepseek-chat"

        cfg = ConfigCenter()
        self._api_key = cfg.get("analysis.deepseek_api_key", "")
        self._model = cfg.get("analysis.deepseek_model", "deepseek-chat")

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    async def analyze(self, symbol: str, name: str = "") -> AnalysisResult:
        """生成股票分析。"""
        result = AnalysisResult(
            symbol=symbol,
            name=name or symbol,
            summary=f"{symbol} 当前走势平稳，建议观望。",
            recommendation="持有",
            key_points=["技术面中性", "关注成交量变化"],
            risk_level="中等",
        )
        bus = await self.bus
        await bus.emit_async("analysis.complete", result.to_dict(), source="analysis")
        return result

    async def answer_question(self, question: str, symbol: str = "") -> StockQA:
        """回答股票问题（口语化）。"""
        qa = StockQA(
            question=question,
            answer=f"关于{symbol or '这只股票'}，建议关注基本面和市场情绪的变化。投资有风险，需谨慎决策。",
            symbol=symbol,
            duration_seconds=30,
        )
        bus = await self.bus
        await bus.emit_async("analysis.qa_answer", qa.to_dict(), source="analysis")
        return qa
