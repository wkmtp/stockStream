"""交易模型。"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Position:
    symbol: str
    quantity: int
    avg_cost: float = 0.0

    @property
    def total_cost(self) -> float:
        return self.quantity * self.avg_cost

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol, "quantity": self.quantity,
            "avg_cost": self.avg_cost,
        }


@dataclass
class Transaction:
    symbol: str
    action: str  # buy / sell
    quantity: int
    price: float
    amount: float = 0.0
    reason: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if not self.amount:
            self.amount = self.quantity * self.price

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol, "action": self.action,
            "quantity": self.quantity, "price": self.price,
            "amount": self.amount, "reason": self.reason,
            "timestamp": self.timestamp,
        }


@dataclass
class Portfolio:
    cash: float = 3000.0
    positions: dict[str, Position] = field(default_factory=dict)
    transactions: list[Transaction] = field(default_factory=list)

    def total_value(self, prices: dict[str, float]) -> float:
        mv = sum(
            pos.quantity * prices.get(pos.symbol, 0)
            for pos in self.positions.values()
        )
        return self.cash + mv

    def to_dict(self) -> dict:
        return {
            "cash": self.cash,
            "positions": {s: p.to_dict() for s, p in self.positions.items()},
        }
