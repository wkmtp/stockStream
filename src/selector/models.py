"""选股策略服务。"""
from __future__ import annotations
from dataclasses import dataclass, field
from src.core.event_bus import EventBus, get_event_bus

import logging
logger = logging.getLogger(__name__)


@dataclass
class SignalCandidate:
    symbol: str = ""
    name: str = ""
    signal: str = ""
    score: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol, "name": self.name,
            "signal": self.signal, "score": self.score, "reason": self.reason,
        }


@dataclass
class SelectorResult:
    candidates: list[SignalCandidate] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "candidates": [c.to_dict() for c in self.candidates],
            "timestamp": self.timestamp,
        }


class SelectorService:
    """选股服务。

    推送事件:
      selector.updated  — 选股结果更新
    """

    def __init__(self, bus: EventBus | None = None) -> None:
        self._bus: EventBus | None = bus

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    async def scan(self) -> SelectorResult:
        """扫描市场，返回推荐标的。"""
        result = SelectorResult(
            candidates=[
                SignalCandidate("600519", "贵州茅台", "BUY", 0.85, "均线金叉"),
            ],
            timestamp="",
        )
        bus = await self.bus
        await bus.emit_async("selector.updated", result.to_dict(), source="selector")
        return result
