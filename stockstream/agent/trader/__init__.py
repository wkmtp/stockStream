"""Trader agent — rule-based portfolio trading.

Public API:
    TraderAgentService   – portfolio lifecycle + trade execution
    TradingRules         – stateless rule engine
    Portfolio / Position / Transaction / EvalResult – data models
"""

from stockstream.agent.trader.engine import TradingRules
from stockstream.agent.trader.models import (
    EvalResult,
    EvalSignal,
    Portfolio,
    Position,
    SignalKind,
    TradeAction,
    TradeSide,
    Transaction,
)
from stockstream.agent.trader.service import TraderAgentService

__all__ = [
    "TraderAgentService",
    "TradingRules",
    "Portfolio",
    "Position",
    "Transaction",
    "EvalResult",
    "EvalSignal",
    "SignalKind",
    "TradeAction",
    "TradeSide",
]
