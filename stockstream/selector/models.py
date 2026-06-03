"""Selector module models for rule-based trading signals."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SignalType(str, Enum):
    """Supported selector signal buckets."""

    OPEN = "open_position"
    ADD = "add_position"
    REDUCE = "reduce_position"
    CLEAR = "clear_position"


@dataclass(slots=True, frozen=True)
class StockFeature:
    """Computed technical and fund-flow features for one stock."""

    symbol: str
    name: str | None = None
    close: float | None = None
    ma20: float | None = None
    ma60: float | None = None
    ma20_deviation_pct: float | None = None
    daily_change_pct: float | None = None
    turnover_pct: float | None = None
    money_flow: float | None = None
    institutional_money_flow: float | None = None
    rsi14: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_golden_cross: bool = False
    macd_dead_cross: bool = False
    shrinking_volume: bool = False


@dataclass(slots=True, frozen=True)
class SignalCandidate:
    """One selected stock plus the values that made it pass the signal rule."""

    symbol: str
    name: str | None
    signal_type: SignalType
    sort_amount: float
    close: float | None
    ma20: float | None
    ma60: float | None
    ma20_deviation_pct: float | None
    daily_change_pct: float | None
    turnover_pct: float | None
    money_flow: float | None
    institutional_money_flow: float | None
    rsi14: float | None
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable candidate representation."""

        return {
            "symbol": self.symbol,
            "name": self.name,
            "signal_type": self.signal_type.value,
            "sort_amount": self.sort_amount,
            "close": self.close,
            "ma20": self.ma20,
            "ma60": self.ma60,
            "ma20_deviation_pct": self.ma20_deviation_pct,
            "daily_change_pct": self.daily_change_pct,
            "turnover_pct": self.turnover_pct,
            "money_flow": self.money_flow,
            "institutional_money_flow": self.institutional_money_flow,
            "rsi14": self.rsi14,
            "reasons": list(self.reasons),
        }


@dataclass(slots=True, frozen=True)
class SelectorReport:
    """Top-N selector report returned by the selector service."""

    top10_open: tuple[SignalCandidate, ...]
    top10_add: tuple[SignalCandidate, ...]
    top10_reduce: tuple[SignalCandidate, ...]
    top10_clear: tuple[SignalCandidate, ...]
    evaluated: int

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable report representation."""

        return {
            "top10_open": [candidate.to_dict() for candidate in self.top10_open],
            "top10_add": [candidate.to_dict() for candidate in self.top10_add],
            "top10_reduce": [candidate.to_dict() for candidate in self.top10_reduce],
            "top10_clear": [candidate.to_dict() for candidate in self.top10_clear],
            "evaluated": self.evaluated,
        }
