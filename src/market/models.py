"""行情数据模型。"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MarketSnapshot:
    """单只股票实时快照。"""
    symbol: str = ""
    name: str = ""
    price: float = 0.0
    change_pct: float = 0.0
    volume: int = 0
    turnover: float = 0.0
    high: float = 0.0
    low: float = 0.0
    open: float = 0.0
    prev_close: float = 0.0
    timestamp: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol, "name": self.name,
            "price": self.price, "change_pct": self.change_pct,
            "volume": self.volume, "high": self.high, "low": self.low,
            "timestamp": self.timestamp,
        }
