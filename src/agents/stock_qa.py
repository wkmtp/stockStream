"""股票问答 Agent。"""
from __future__ import annotations
import logging
from dataclasses import dataclass

from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


@dataclass
class QAAnswer:
    question: str = ""
    answer: str = ""
    symbol: str = ""
    duration_seconds: int = 30
    username: str = ""

    def to_dict(self) -> dict:
        return {
            "question": self.question, "answer": self.answer,
            "symbol": self.symbol, "duration_seconds": self.duration_seconds,
            "username": self.username,
        }


class StockQAAgent:
    """股票问答 Agent — 自动回答用户股票提问。

    监听事件:
      danmu.processed (tag=stock_question) → 自动回答
    推送事件:
      analysis.qa_answer → 口语化回答
    """

    _STOCK_NAME_MAP = {
        "茅台": "600519", "贵州茅台": "600519",
        "平安银行": "000001", "深发展": "000001",
        "宁德时代": "300750", "宁德": "300750",
        "比亚迪": "002594",
        "五粮液": "000858",
        "招商银行": "600036",
    }

    def __init__(self, bus: EventBus | None = None) -> None:
        self._bus: EventBus | None = bus
        self._qa_count = 0

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    async def start(self) -> None:
        bus = await self.bus

        @bus.on("danmu.processed")
        async def _on_danmu(event):
            data = event.data or {}
            tags = data.get("tags", [])
            if "stock_question" in tags:
                await self._handle_question(event)

        logger.info("StockQAAgent started")

    async def _handle_question(self, event) -> None:
        data = event.data or {}
        content = data.get("content", "")
        username = data.get("username", "")

        symbol = self._extract_symbol(content)
        stock_name = symbol
        for name, code in self._STOCK_NAME_MAP.items():
            if code == symbol:
                stock_name = name
                break

        # 生成口语化回答
        answers = [
            f"感谢{username}的提问！{stock_name}目前走势稳健，建议关注均线支撑和成交量的配合。短期操作须谨慎，控制仓位。",
            f"{username}问得很好！{stock_name}最近在关键位置，突破上方压力位可考虑参与，跌破支撑则注意风险。",
            f"{username}你好！{stock_name}基本面不错，技术面看处于震荡整理阶段，耐心持有，等待方向明确。",
        ]

        import random
        answer = QAAnswer(
            question=content,
            answer=random.choice(answers),
            symbol=symbol,
            duration_seconds=30,
            username=username,
        )

        self._qa_count += 1
        bus = await self.bus
        await bus.emit_async("analysis.qa_answer", answer.to_dict(), source="stock_qa")

    def _extract_symbol(self, text: str) -> str:
        """从文本中提取股票代码或名称。"""
        for name, code in self._STOCK_NAME_MAP.items():
            if name in text:
                return code

        # 尝试匹配纯数字代码
        import re
        match = re.search(r'\b(\d{6})\b', text)
        if match:
            return match.group(1)

        return "000001"  # default

    def get_stats(self) -> dict:
        return {"questions_answered": self._qa_count}
