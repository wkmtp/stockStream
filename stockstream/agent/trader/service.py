"""TraderAgentService — portfolio management with rule-based signals.

All mutations (buy/sell) are recorded as transactions and persisted to
portfolio.json immediately.  Every signal evaluation is stateless and
can be called as frequently as each market tick.
"""

from __future__ import annotations

import logging
from typing import Any

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
    _txn_id,
)
from stockstream.agent.trader.repository import PortfolioRepository

logger = logging.getLogger(__name__)


class TraderAgentService:
    """Full trading agent: portfolio lifecycle + rule evaluation.

    Usage::

        trader = TraderAgentService()
        trader.load()

        # suggest actions
        result = trader.evaluate_all()

        # execute trades
        trader.open("000001", "平安银行", 13.0, 100)
        trader.add("000001", 12.5, 100)
        trader.take_profit_half("000001", 14.95)
        trader.close("000001", 11.7, TradeAction.STOP_LOSS)
    """

    DEFAULT_CASH = 3000.0

    def __init__(self, json_path: str | None = None) -> None:
        self._repo = PortfolioRepository(json_path)
        self._rules = TradingRules()
        self._portfolio: Portfolio = Portfolio(
            cash=self.DEFAULT_CASH,
            initial_capital=self.DEFAULT_CASH,
        )
        self._loaded = False

    # ── lifecycle ──────────────────────────────────────────────────

    def load(self) -> Portfolio:
        """Load portfolio from disk."""
        self._portfolio = self._repo.load()
        self._loaded = True
        logger.info(
            "Portfolio loaded: cash=%.2f positions=%d value=%.2f",
            self._portfolio.cash,
            len(self._portfolio.positions),
            self._portfolio.total_value,
        )
        return self._portfolio

    def save(self) -> None:
        """Persist current state."""
        self._repo.save(self._portfolio)

    @property
    def portfolio(self) -> Portfolio:
        if not self._loaded:
            self.load()
        return self._portfolio

    def get_portfolio_dict(self) -> dict[str, Any]:
        return self.portfolio.to_dict()

    # ── evaluation ─────────────────────────────────────────────────

    def evaluate_all(self) -> EvalResult:
        """Evaluate trade signals for all held positions."""
        return self._rules.evaluate_all(self.portfolio)

    def can_open(self, amount: float) -> tuple[bool, str]:
        """Check if a new position of *amount* CNY can be opened."""
        return self._rules.can_open_position(self.portfolio, amount)

    def max_add(self) -> float:
        """Return max additional amount that fits the 30% cap."""
        return self._rules.max_add_amount(self.portfolio)

    # ── buy-side actions ───────────────────────────────────────────

    def open(self, symbol: str, name: str, price: float, shares: int) -> dict[str, Any]:
        """Open a new position (建仓).

        Args:
            symbol: Stock code.
            name:   Human-readable stock name.
            price:  Entry price per share.
            shares: Number of shares to buy (integer lot).
        """
        p = self.portfolio
        symbol = symbol.upper()
        amount = round(price * shares, 2)

        if symbol in p.positions:
            return {"ok": False, "error": f"{symbol} 已持仓，请使用补仓操作"}
        ok, reason = self._rules.can_open_position(p, amount)
        if not ok:
            return {"ok": False, "error": reason}

        # Deduct cash
        p.cash = round(p.cash - amount, 2)
        pos = Position(symbol=symbol, name=name, shares=shares, avg_cost=price, current_price=price)
        p.positions[symbol] = pos

        txn = Transaction(
            id=_txn_id(),
            symbol=symbol,
            side=TradeSide.BUY,
            action=TradeAction.OPEN,
            shares=shares,
            price=price,
            amount=amount,
        )
        p.transactions.append(txn)
        self.save()
        logger.info("OPEN %s %d股@%.2f 金额=%.2f", symbol, shares, price, amount)
        return {"ok": True, "transaction": txn.to_dict(), "portfolio": p.to_dict()}

    def add(self, symbol: str, price: float, shares: int) -> dict[str, Any]:
        """Add to an existing position (补仓), averaging down.

        Only allowed when unrealized loss ≤ 8%.
        """
        p = self.portfolio
        symbol = symbol.upper()
        amount = round(price * shares, 2)
        pos = p.get_position(symbol)

        if pos is None:
            return {"ok": False, "error": f"{symbol} 未持仓，请先建仓"}

        # Check add condition: loss ≤ 8%
        old_pnl_pct = pos.unrealized_pnl_pct
        if old_pnl_pct < 0 and abs(old_pnl_pct) > self._rules.ADD_LOSS_CAP:
            return {
                "ok": False,
                "error": f"亏损{old_pnl_pct}%已超过{self._rules.ADD_LOSS_CAP}%补仓上限，不建议补仓",
            }

        ok, reason = self._rules.can_open_position(p, amount)
        if not ok:
            return {"ok": False, "error": reason}

        # Update average cost and cash
        total_cost = pos.cost_basis + amount
        total_shares = pos.shares + shares
        new_avg = round(total_cost / total_shares, 4)

        p.cash = round(p.cash - amount, 2)
        pos.shares = total_shares
        pos.avg_cost = new_avg
        pos.current_price = price

        txn = Transaction(
            id=_txn_id(),
            symbol=symbol,
            side=TradeSide.BUY,
            action=TradeAction.ADD,
            shares=shares,
            price=price,
            amount=amount,
        )
        p.transactions.append(txn)
        self.save()
        logger.info(
            "ADD %s %d股@%.2f 新均价=%.4f (原亏损%.2f%%)",
            symbol, shares, price, new_avg, old_pnl_pct,
        )
        return {"ok": True, "transaction": txn.to_dict(), "portfolio": p.to_dict()}

    # ── sell-side actions ──────────────────────────────────────────

    def take_profit_half(self, symbol: str, price: float) -> dict[str, Any]:
        """Sell half of a position at target price (止盈15%)."""
        return self._sell(
            symbol=symbol,
            price=price,
            shares_fn=lambda pos: self._rules.tp_half_shares(pos),
            action=TradeAction.TAKE_PROFIT_HALF,
        )

    def take_profit_full(self, symbol: str, price: float) -> dict[str, Any]:
        """Sell entire position at target price (止盈25%)."""
        return self._sell(
            symbol=symbol,
            price=price,
            shares_fn=lambda pos: pos.shares,
            action=TradeAction.TAKE_PROFIT_FULL,
        )

    def stop_loss(self, symbol: str, price: float) -> dict[str, Any]:
        """Sell entire position at stop-loss price (止损)."""
        return self._sell(
            symbol=symbol,
            price=price,
            shares_fn=lambda pos: pos.shares,
            action=TradeAction.STOP_LOSS,
        )

    def close(self, symbol: str, price: float, action: TradeAction = TradeAction.MANUAL) -> dict[str, Any]:
        """Sell entire position with a custom action label."""
        return self._sell(
            symbol=symbol,
            price=price,
            shares_fn=lambda pos: pos.shares,
            action=action,
        )

    def _sell(
        self,
        symbol: str,
        price: float,
        shares_fn,
        action: TradeAction,
    ) -> dict[str, Any]:
        """Internal shared sell logic."""
        p = self.portfolio
        symbol = symbol.upper()
        pos = p.get_position(symbol)
        if pos is None:
            return {"ok": False, "error": f"{symbol} 未持仓"}

        sell_shares = shares_fn(pos)
        if sell_shares <= 0:
            return {"ok": False, "error": "卖出股数必须 > 0"}
        sell_shares = min(sell_shares, pos.shares)
        amount = round(sell_shares * price, 2)

        p.cash = round(p.cash + amount, 2)
        pos.shares -= sell_shares
        pos.current_price = price

        # Remove position if fully sold
        if pos.shares <= 0:
            del p.positions[symbol]

        txn = Transaction(
            id=_txn_id(),
            symbol=symbol,
            side=TradeSide.SELL,
            action=action,
            shares=sell_shares,
            price=price,
            amount=amount,
        )
        p.transactions.append(txn)
        self.save()
        logger.info("%s %s %d股@%.2f 金额=%.2f", action.value, symbol, sell_shares, price, amount)
        return {"ok": True, "transaction": txn.to_dict(), "portfolio": p.to_dict()}

    # ── helpers ────────────────────────────────────────────────────

    def update_price(self, symbol: str, price: float) -> None:
        """Update current price for an existing position."""
        pos = self.portfolio.get_position(symbol)
        if pos:
            pos.current_price = price

    def update_prices(self, prices: dict[str, float]) -> None:
        """Batch update current prices."""
        for symbol, price in prices.items():
            self.update_price(symbol, price)

    def get_position(self, symbol: str) -> dict[str, Any] | None:
        pos = self.portfolio.get_position(symbol)
        return pos.to_dict() if pos else None

    def reset(self) -> Portfolio:
        """Reset portfolio to initial state (for testing)."""
        self._portfolio = Portfolio(
            cash=self.DEFAULT_CASH,
            initial_capital=self.DEFAULT_CASH,
        )
        self.save()
        return self._portfolio
