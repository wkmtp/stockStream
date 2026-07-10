"""Trader agent data models: portfolio, positions, transactions, signals.

Design principles:
- All monetary values in CNY (元).
- "total capital" = cash + market_value of all positions.
- Position sizing rules are expressed as ratios of initial_capital (3000).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# ── enums ────────────────────────────────────────────────────────────


class TradeSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class TradeAction(str, Enum):
    """Semantic label attached to every trade."""

    OPEN = "open"               # 建仓
    ADD = "add"                 # 补仓
    TAKE_PROFIT_HALF = "tp_half"   # 止盈15%卖一半
    TAKE_PROFIT_FULL = "tp_full"   # 止盈25%清仓
    STOP_LOSS = "stop_loss"        # 止损-10%
    MANUAL = "manual"              # 手动交易


class SignalKind(str, Enum):
    """Evaluation result for a held position."""

    HOLD = "hold"                  # 继续持有
    ADD = "add"                    # 建议补仓
    TP_HALF = "tp_half"            # 止盈一半
    TP_FULL = "tp_full"            # 止盈清仓
    STOP_LOSS = "stop_loss"        # 止损清仓
    NONE = "none"                  # 无持仓


# ── data containers ──────────────────────────────────────────────────


@dataclass()
class Position:
    """A single stock holding."""

    symbol: str
    name: str
    shares: int
    avg_cost: float           # 持仓均价
    current_price: float = 0.0

    @property
    def cost_basis(self) -> float:
        return round(self.shares * self.avg_cost, 2)

    @property
    def market_value(self) -> float:
        return round(self.shares * self.current_price, 2)

    @property
    def unrealized_pnl(self) -> float:
        return round(self.market_value - self.cost_basis, 2)

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.cost_basis == 0:
            return 0.0
        return round(self.unrealized_pnl / self.cost_basis * 100, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "shares": self.shares,
            "avg_cost": self.avg_cost,
            "current_price": self.current_price,
            "cost_basis": self.cost_basis,
            "market_value": self.market_value,
            "unrealized_pnl": self.unrealized_pnl,
            "unrealized_pnl_pct": self.unrealized_pnl_pct,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Position:
        return cls(
            symbol=data["symbol"],
            name=data.get("name", ""),
            shares=data["shares"],
            avg_cost=data["avg_cost"],
            current_price=data.get("current_price", 0.0),
        )


@dataclass()
class Transaction:
    """A single completed trade."""

    id: str
    symbol: str
    side: TradeSide
    action: TradeAction
    shares: int
    price: float
    amount: float
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side.value,
            "action": self.action.value,
            "shares": self.shares,
            "price": self.price,
            "amount": self.amount,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Transaction:
        return cls(
            id=data["id"],
            symbol=data["symbol"],
            side=TradeSide(data["side"]),
            action=TradeAction(data["action"]),
            shares=data["shares"],
            price=data["price"],
            amount=data["amount"],
            timestamp=data.get("timestamp", ""),
        )


@dataclass()
class Portfolio:
    """Full trading portfolio state."""

    cash: float
    initial_capital: float
    positions: dict[str, Position] = field(default_factory=dict)
    transactions: list[Transaction] = field(default_factory=list)

    @property
    def total_market_value(self) -> float:
        return round(sum(p.market_value for p in self.positions.values()), 2)

    @property
    def total_value(self) -> float:
        return round(self.cash + self.total_market_value, 2)

    @property
    def total_pnl(self) -> float:
        return round(self.total_value - self.initial_capital, 2)

    @property
    def total_pnl_pct(self) -> float:
        if self.initial_capital == 0:
            return 0.0
        return round(self.total_pnl / self.initial_capital * 100, 2)

    @property
    def position_ratio(self) -> float:
        """Current position as a fraction of initial capital."""
        if self.initial_capital == 0:
            return 0.0
        return round(self.total_market_value / self.initial_capital * 100, 2)

    def get_position(self, symbol: str) -> Position | None:
        return self.positions.get(symbol.upper())

    def to_dict(self) -> dict[str, Any]:
        return {
            "cash": self.cash,
            "initial_capital": self.initial_capital,
            "total_value": self.total_value,
            "total_market_value": self.total_market_value,
            "total_pnl": self.total_pnl,
            "total_pnl_pct": self.total_pnl_pct,
            "position_ratio": self.position_ratio,
            "positions": {k: v.to_dict() for k, v in self.positions.items()},
            "transactions": [t.to_dict() for t in self.transactions],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Portfolio:
        positions = {
            k: Position.from_dict(v) for k, v in data.get("positions", {}).items()
        }
        transactions = [
            Transaction.from_dict(t) for t in data.get("transactions", [])
        ]
        return cls(
            cash=data["cash"],
            initial_capital=data.get("initial_capital", data["cash"]),
            positions=positions,
            transactions=transactions,
        )


@dataclass()
class EvalSignal:
    """Result of evaluating trading rules against a position."""

    symbol: str
    kind: SignalKind
    current_price: float
    profit_pct: float
    suggestion: str
    rule_detail: str = ""


@dataclass()
class EvalResult:
    """Batch evaluation result for all held positions."""

    portfolio_value: float
    cash: float
    position_ratio: float
    total_pnl_pct: float
    signals: list[EvalSignal] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "portfolio_value": self.portfolio_value,
            "cash": self.cash,
            "position_ratio": self.position_ratio,
            "total_pnl_pct": self.total_pnl_pct,
            "signals": [
                {
                    "symbol": s.symbol,
                    "kind": s.kind.value,
                    "current_price": s.current_price,
                    "profit_pct": s.profit_pct,
                    "suggestion": s.suggestion,
                    "rule_detail": s.rule_detail,
                }
                for s in self.signals
            ],
            "timestamp": self.timestamp,
        }


# ── helpers ──────────────────────────────────────────────────────────


def _txn_id() -> str:
    return f"txn_{uuid.uuid4().hex[:8]}"
