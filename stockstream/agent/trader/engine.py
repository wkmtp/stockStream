"""Trading rule engine implementing strict position-sizing and risk management.

Rules (hard-coded per specification):
    - 建仓 (open):  total market value ≤ 30% of initial capital (3000).
    - 补仓 (add):   unrealized loss ≤ 8% on existing position.
    - 止盈 (tp):    +15% → sell half;  +25% → sell all.
    - 止损 (sl):    -10% → sell all.

Every rule returns a concrete suggestion: SignalKind + actionable message.
"""

from __future__ import annotations

from stockstream.agent.trader.models import (
    EvalResult,
    EvalSignal,
    Portfolio,
    Position,
    SignalKind,
)


class TradingRules:
    """Stateless rule evaluator.

    Initial capital and position cap are fixed at 3000 / 30%.
    """

    INITIAL_CAPITAL: float = 3000.0
    MAX_POSITION_RATIO: float = 0.30       # 30% of initial capital
    ADD_LOSS_CAP: float = 8.0               # 补仓仅限亏损≤8%
    TP_HALF: float = 15.0                   # +15% 卖一半
    TP_FULL: float = 25.0                   # +25% 清仓
    STOP_LOSS: float = -10.0                # -10% 止损

    # ── position sizer ──────────────────────────────────────────────

    def max_position_value(self, portfolio: Portfolio) -> float:
        """Maximum total market value allowed (元)."""
        return round(self.INITIAL_CAPITAL * self.MAX_POSITION_RATIO, 2)

    def available_position_value(self, portfolio: Portfolio) -> float:
        """Remaining position budget (元)."""
        return round(self.max_position_value(portfolio) - portfolio.total_market_value, 2)

    def can_open_position(self, portfolio: Portfolio, amount: float) -> tuple[bool, str]:
        """Check whether a new position of *amount* CNY fits the 30% cap."""
        if amount <= 0:
            return False, "买入金额必须 > 0"
        available = self.available_position_value(portfolio)
        if amount > available:
            return False, (
                f"总仓位已达{portfolio.position_ratio}%，"
                f"剩余额度{available:.0f}元，本次{amount:.0f}元超出限制"
            )
        if amount > portfolio.cash:
            return False, f"可用资金不足: 现金{portfolio.cash:.0f}元 < 买入{amount:.0f}元"
        return True, f"可建仓，买入{amount:.0f}元后仓位{(portfolio.total_market_value + amount) / self.INITIAL_CAPITAL * 100:.1f}%"

    # ── single-position checks ──────────────────────────────────────

    def evaluate(self, position: Position) -> EvalSignal:
        """Evaluate all rules for a single position, return the strongest signal.

        Priority: STOP_LOSS > TP_FULL > TP_HALF > ADD > HOLD
        """
        pnl_pct = position.unrealized_pnl_pct

        # Stop loss always has top priority
        if pnl_pct <= self.STOP_LOSS:
            return EvalSignal(
                symbol=position.symbol,
                kind=SignalKind.STOP_LOSS,
                current_price=position.current_price,
                profit_pct=pnl_pct,
                suggestion=f"触发止损({pnl_pct}%≤-10%)，建议全部卖出",
                rule_detail=f"持仓成本{position.avg_cost}，现价{position.current_price}，亏损{pnl_pct}%",
            )

        # Take profit — full clear
        if pnl_pct >= self.TP_FULL and position.shares > 0:
            return EvalSignal(
                symbol=position.symbol,
                kind=SignalKind.TP_FULL,
                current_price=position.current_price,
                profit_pct=pnl_pct,
                suggestion=f"触发满仓止盈({pnl_pct}%≥25%)，建议全部卖出",
                rule_detail=f"持仓成本{position.avg_cost}，现价{position.current_price}，盈利{pnl_pct}%",
            )

        # Take profit — half
        if pnl_pct >= self.TP_HALF and position.shares > 0:
            return EvalSignal(
                symbol=position.symbol,
                kind=SignalKind.TP_HALF,
                current_price=position.current_price,
                profit_pct=pnl_pct,
                suggestion=f"触发半仓止盈({pnl_pct}%≥15%)，建议卖出一半",
                rule_detail=f"持仓成本{position.avg_cost}，现价{position.current_price}，盈利{pnl_pct}%",
            )

        # Add (averaging down) — only when loss ≤ 8%
        if pnl_pct < 0 and abs(pnl_pct) <= self.ADD_LOSS_CAP:
            return EvalSignal(
                symbol=position.symbol,
                kind=SignalKind.ADD,
                current_price=position.current_price,
                profit_pct=pnl_pct,
                suggestion=f"亏损{pnl_pct}%≤8%，可考虑补仓拉低成本",
                rule_detail=f"持仓成本{position.avg_cost}，现价{position.current_price}，亏损在可控范围",
            )

        # Hold
        return EvalSignal(
            symbol=position.symbol,
            kind=SignalKind.HOLD,
            current_price=position.current_price,
            profit_pct=pnl_pct,
            suggestion="继续持有",
            rule_detail=f"盈利{pnl_pct}%，未触发止盈/止损/补仓条件",
        )

    def evaluate_all(self, portfolio: Portfolio) -> EvalResult:
        """Evaluate all positions in the portfolio."""
        signals: list[EvalSignal] = []
        for position in portfolio.positions.values():
            signals.append(self.evaluate(position))
        return EvalResult(
            portfolio_value=portfolio.total_value,
            cash=portfolio.cash,
            position_ratio=portfolio.position_ratio,
            total_pnl_pct=portfolio.total_pnl_pct,
            signals=signals,
        )

    # ── compute trade size ──────────────────────────────────────────

    def tp_half_shares(self, position: Position) -> int:
        """Number of shares to sell for half take-profit (ceil)."""
        return (position.shares + 1) // 2

    def tp_full_shares(self, position: Position) -> int:
        """Number of shares to sell for full take-profit / stop-loss."""
        return position.shares

    def max_add_amount(self, portfolio: Portfolio) -> float:
        """Maximum add amount given remaining position budget and cash."""
        available = min(self.available_position_value(portfolio), portfolio.cash)
        return max(available, 0.0)
