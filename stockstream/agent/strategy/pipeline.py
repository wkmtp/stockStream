"""AutoTradingPipeline — autonomous trading loop.

Connects market (real-time prices), selector (technical signals), and
trader (position-sizing rules) into one background tick loop.

Pipeline per-tick order:
    1. Sync latest spot prices → trader portfolio
    2. Evaluate trader rules for all held positions
    3. Auto-execute: STOP_LOSS > TP_FULL > TP_HALF (hard rules)
    4. Pull selector report (OPEN / ADD / REDUCE / CLEAR candidates)
    5. Cross-reference held positions with selector REDUCE / CLEAR
    6. Auto-add when both trader ADD signal AND selector ADD agree
    7. Auto-open new positions from selector OPEN (budget permitting)
    8. Persist portfolio
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from stockstream.agent.trader.models import SignalKind
from stockstream.agent.trader.service import TraderAgentService
from stockstream.selector.models import SignalCandidate, SignalType, SelectorReport
from stockstream.selector.service import SelectorService

logger = logging.getLogger(__name__)

# Minimum shares per trade (A-share lot)
LOT_SIZE = 100


@dataclass
class TickAction:
    """A single trade decision taken during a pipeline tick."""

    kind: str  # "open" | "add" | "tp_half" | "tp_full" | "stop_loss" | "reduce" | "clear" | "skip"
    symbol: str
    reason: str
    price: float = 0.0
    shares: int = 0
    amount: float = 0.0
    success: bool = False
    error: str = ""


@dataclass
class TickReport:
    """Summary of one pipeline tick cycle."""

    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    phase: str = ""  # "idle" | "pre_open" | "trading" | "post_close"
    actions: list[TickAction] = field(default_factory=list)
    selector_summary: dict[str, int] = field(default_factory=dict)
    trader_summary: dict[str, Any] = field(default_factory=dict)
    portfolio_snapshot: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "phase": self.phase,
            "actions": [
                {
                    "kind": a.kind,
                    "symbol": a.symbol,
                    "reason": a.reason,
                    "price": a.price,
                    "shares": a.shares,
                    "amount": a.amount,
                    "success": a.success,
                    "error": a.error,
                }
                for a in self.actions
            ],
            "selector_summary": self.selector_summary,
            "trader_summary": self.trader_summary,
            "portfolio_snapshot": self.portfolio_snapshot,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


NO_REPORT = SelectorReport(
    top10_open=(), top10_add=(), top10_reduce=(), top10_clear=(), evaluated=0,
)


class AutoTradingPipeline:
    """Background loop that evaluates rules and executes trades automatically.

    Usage::

        pipeline = AutoTradingPipeline(
            market_storage=market.storage,
            selector=selector,
            trader=trader,
        )
        await pipeline.start()
        await pipeline.stop()
    """

    def __init__(
        self,
        market_storage: Any,
        selector: SelectorService,
        trader: TraderAgentService,
        *,
        tick_seconds: float = 10.0,
        auto_open: bool = True,
        auto_add: bool = True,
        auto_reduce: bool = False,
        auto_clear: bool = True,
        report_dir: str | None = None,
    ) -> None:
        self._storage = market_storage
        self._selector = selector
        self._trader = trader
        self._tick_seconds = tick_seconds
        self._auto_open = auto_open
        self._auto_add = auto_add
        self._auto_reduce = auto_reduce
        self._auto_clear = auto_clear
        self._report_dir = report_dir
        self._task: asyncio.Task | None = None
        self._running = False
        self._tick_count = 0
        self._last_report: TickReport | None = None
        self._phase = "idle"

    # ── lifecycle ──────────────────────────────────────────────────

    @property
    def running(self) -> bool:
        return self._running

    @property
    def tick_count(self) -> int:
        return self._tick_count

    @property
    def last_report(self) -> TickReport | None:
        return self._last_report

    @property
    def phase(self) -> str:
        return self._phase

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("AutoTradingPipeline started (tick=%.1fs)", self._tick_seconds)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("AutoTradingPipeline stopped after %d ticks", self._tick_count)

    async def _loop(self) -> None:
        while self._running:
            t0 = datetime.now(timezone.utc)
            try:
                report = await self._tick()
                self._last_report = report
                self._tick_count += 1
                await self._write_report(report)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Pipeline tick %d failed", self._tick_count + 1)
            elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
            wait = max(0.5, self._tick_seconds - elapsed)
            await asyncio.sleep(wait)

    # ── tick logic ─────────────────────────────────────────────────

    async def _tick(self) -> TickReport:
        report = TickReport(phase=self._phase)
        t0 = datetime.now(timezone.utc)

        # 1. Sync prices
        await self._sync_prices(report)

        # 2. Evaluate trader rules (auto-execute stop-loss / take-profit)
        await self._auto_trader_rules(report)

        # 3. Pull selector signals
        sel_report = await self._safe_selector_report()
        report.selector_summary = {
            "open": len(sel_report.top10_open),
            "add": len(sel_report.top10_add),
            "reduce": len(sel_report.top10_reduce),
            "clear": len(sel_report.top10_clear),
            "evaluated": sel_report.evaluated,
        }

        # 4. Cross-reference selector REDUCE / CLEAR with held positions
        if self._auto_clear or self._auto_reduce:
            await self._cross_clear_reduce(report, sel_report)

        # 5. Auto-add when trader + selector agree
        if self._auto_add:
            await self._cross_add(report, sel_report)

        # 6. Auto-open new positions from selector OPEN
        if self._auto_open:
            await self._auto_open_positions(report, sel_report)

        # 7. Persist & snapshot
        self._trader.save()
        report.portfolio_snapshot = _portfolio_snapshot(self._trader)
        report.trader_summary = self._trader.evaluate_all().to_dict()
        report.duration_ms = round(
            (datetime.now(timezone.utc) - t0).total_seconds() * 1000, 1,
        )
        return report

    # ── step 1: sync prices ────────────────────────────────────────

    async def _sync_prices(self, report: TickReport) -> None:
        """Pull latest spot prices for held positions and update portfolio."""
        positions = list(self._trader.portfolio.positions.keys())
        if not positions:
            return
        try:
            prices = await self._fetch_latest_prices(positions)
            if prices:
                self._trader.update_prices(prices)
                logger.debug("Synced %d position prices", len(prices))
        except Exception:
            logger.exception("Price sync failed")

    async def _fetch_latest_prices(self, symbols: list[str]) -> dict[str, float]:
        """Extract latest close/price from spot cache for given symbols."""
        from stockstream.market.models import MarketDataset

        try:
            rows = await self._storage.latest(MarketDataset.SPOT, limit=200)
        except Exception:
            logger.warning("Failed to read spot cache", exc_info=True)
            return {}

        prices: dict[str, float] = {}
        seen: set[str] = set()
        target = set(s.upper() for s in symbols)
        for row in rows:
            symbol = str(row.get("symbol", "")).upper()
            if symbol in seen or symbol not in target:
                continue
            payload = row.get("payload", {})
            price = _extract_price(payload)
            if price and price > 0:
                prices[symbol] = price
                seen.add(symbol)
            if seen == target:
                break
        return prices

    # ── step 2: auto trader rules ──────────────────────────────────

    async def _auto_trader_rules(self, report: TickReport) -> None:
        """Evaluate trader rules and auto-execute stop-loss / take-profit.

        These are hard risk-management rules — always execute immediately.
        """
        result = self._trader.evaluate_all()
        for signal in result.signals:
            pos = self._trader.portfolio.get_position(signal.symbol)
            if pos is None:
                continue
            price = signal.current_price or pos.current_price
            if price <= 0:
                continue
            pos_shares = pos.shares  # snapshot before sell modifies it

            if signal.kind == SignalKind.STOP_LOSS:
                amount = round(pos_shares * price, 2)
                action = self._trader.stop_loss(signal.symbol, price)
                report.actions.append(TickAction(
                    kind="stop_loss",
                    symbol=signal.symbol,
                    reason=f"止损 | 亏损{signal.profit_pct:.1f}%≤-10% | {signal.rule_detail}",
                    price=price,
                    shares=pos_shares,
                    amount=amount,
                    success=action.get("ok", False),
                    error=action.get("error", ""),
                ))

            elif signal.kind == SignalKind.TP_FULL:
                amount = round(pos_shares * price, 2)
                action = self._trader.take_profit_full(signal.symbol, price)
                report.actions.append(TickAction(
                    kind="tp_full",
                    symbol=signal.symbol,
                    reason=f"满仓止盈 | 盈利{signal.profit_pct:.1f}%≥25% | {signal.rule_detail}",
                    price=price,
                    shares=pos_shares,
                    amount=amount,
                    success=action.get("ok", False),
                    error=action.get("error", ""),
                ))

            elif signal.kind == SignalKind.TP_HALF:
                half = (pos_shares + 1) // 2
                amount = round(half * price, 2)
                action = self._trader.take_profit_half(signal.symbol, price)
                report.actions.append(TickAction(
                    kind="tp_half",
                    symbol=signal.symbol,
                    reason=f"半仓止盈 | 盈利{signal.profit_pct:.1f}%≥15% | {signal.rule_detail}",
                    price=price,
                    shares=half,
                    amount=amount,
                    success=action.get("ok", False),
                    error=action.get("error", ""),
                ))

    # ── step 4: cross clear/reduce ─────────────────────────────────

    async def _cross_clear_reduce(
        self, report: TickReport, sel: SelectorReport,
    ) -> None:
        """When selector says REDUCE or CLEAR for a held stock, act on it."""
        held = set(self._trader.portfolio.positions.keys())

        # CLEAR signals: sell entire position when selector AND rules agree
        for c in sel.top10_clear:
            if c.symbol.upper() not in held:
                continue
            price = c.close or 0
            if price <= 0:
                continue
            pos = self._trader.portfolio.get_position(c.symbol.upper())
            if pos is None:
                continue
            pos_shares = pos.shares  # snapshot before sell
            pos_amount = round(pos_shares * price, 2)
            if self._auto_clear:
                action = self._trader.close(c.symbol.upper(), price)
                report.actions.append(TickAction(
                    kind="clear",
                    symbol=c.symbol.upper(),
                    reason=f"selector清仓信号: {', '.join(c.reasons)}",
                    price=price,
                    shares=pos_shares,
                    amount=pos_amount,
                    success=action.get("ok", False),
                    error=action.get("error", ""),
                ))
            else:
                report.actions.append(TickAction(
                    kind="clear",
                    symbol=c.symbol.upper(),
                    reason=f"[DRY-RUN] selector清仓: {', '.join(c.reasons)}",
                ))

        # REDUCE signals: sell half when selector says reduce
        held_after = set(self._trader.portfolio.positions.keys())
        for c in sel.top10_reduce:
            if c.symbol.upper() not in held_after:
                continue
            price = c.close or 0
            if price <= 0:
                continue
            pos = self._trader.portfolio.get_position(c.symbol.upper())
            if pos is None:
                continue
            half = (pos.shares + 1) // 2
            half_amount = round(half * price, 2)
            if self._auto_reduce:
                action = self._trader.take_profit_half(c.symbol.upper(), price)
                report.actions.append(TickAction(
                    kind="reduce",
                    symbol=c.symbol.upper(),
                    reason=f"selector减仓: {', '.join(c.reasons)}",
                    price=price,
                    shares=half,
                    amount=half_amount,
                    success=action.get("ok", False),
                    error=action.get("error", ""),
                ))
            else:
                report.actions.append(TickAction(
                    kind="reduce",
                    symbol=c.symbol.upper(),
                    reason=f"[DRY-RUN] selector减仓: {', '.join(c.reasons)}",
                ))

    # ── step 5: cross add ──────────────────────────────────────────

    async def _cross_add(self, report: TickReport, sel: SelectorReport) -> None:
        """Auto-add when both trader ADD signal and selector ADD agree."""
        held = set(self._trader.portfolio.positions.keys())
        sel_add_map: dict[str, SignalCandidate] = {
            c.symbol.upper(): c for c in sel.top10_add
        }

        result = self._trader.evaluate_all()
        for signal in result.signals:
            if signal.kind != SignalKind.ADD:
                continue
            sym = signal.symbol.upper()
            if sym not in held:
                continue
            if sym not in sel_add_map:
                continue  # selector doesn't agree, skip

            sel_candidate = sel_add_map[sym]
            price = sel_candidate.close or signal.current_price
            if price <= 0:
                continue

            # Position size
            budget = self._trader.max_add()
            if budget < price * LOT_SIZE:
                report.actions.append(TickAction(
                    kind="add",
                    symbol=sym,
                    reason=f"补仓额度不足: 可用{budget:.0f}元 < {price * LOT_SIZE:.0f}元(1手)",
                    error=f"预算={budget:.0f}, 需要>={price * LOT_SIZE:.0f}",
                ))
                continue

            max_shares = int(budget / price / LOT_SIZE) * LOT_SIZE
            shares = max(LOT_SIZE, max_shares)
            if shares < LOT_SIZE:
                continue

            action = self._trader.add(sym, price, shares)
            report.actions.append(TickAction(
                kind="add",
                symbol=sym,
                reason=f"trader+selector双重确认补仓: {', '.join(sel_candidate.reasons)}",
                price=price,
                shares=shares,
                amount=round(shares * price, 2),
                success=action.get("ok", False),
                error=action.get("error", ""),
            ))

    # ── step 6: auto open ──────────────────────────────────────────

    async def _auto_open_positions(
        self, report: TickReport, sel: SelectorReport,
    ) -> None:
        """Open new positions from selector OPEN candidates, budget permitting."""
        held = set(self._trader.portfolio.positions.keys())

        for c in sel.top10_open:
            sym = c.symbol.upper()
            if sym in held:
                continue
            price = c.close or 0
            if price <= 0:
                continue

            # Check trader budget
            amount_est = price * LOT_SIZE
            ok, reason = self._trader.can_open(amount_est)
            if not ok:
                report.actions.append(TickAction(
                    kind="open",
                    symbol=sym,
                    reason=f"[SKIP] {reason}",
                    price=price,
                    error=reason,
                ))
                continue

            budget = self._trader.max_add()
            max_shares = int(budget / price / LOT_SIZE) * LOT_SIZE
            shares = max(LOT_SIZE, max_shares)
            if shares < LOT_SIZE:
                continue

            action = self._trader.open(
                symbol=sym,
                name=c.name or sym,
                price=price,
                shares=shares,
            )
            report.actions.append(TickAction(
                kind="open",
                symbol=sym,
                reason=f"selector建仓信号: {', '.join(c.reasons)}",
                price=price,
                shares=shares,
                amount=round(shares * price, 2),
                success=action.get("ok", False),
                error=action.get("error", ""),
            ))

    # ── helpers ────────────────────────────────────────────────────

    async def _safe_selector_report(self) -> SelectorReport:
        try:
            return await self._selector.generate_signals(top_n=10)
        except Exception:
            logger.warning("Selector report generation failed", exc_info=True)
            return NO_REPORT

    async def _write_report(self, report: TickReport) -> None:
        if not self._report_dir:
            return
        try:
            import os
            os.makedirs(self._report_dir, exist_ok=True)
            path = os.path.join(self._report_dir, "trading_log.jsonl")
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(report.to_dict(), ensure_ascii=False) + "\n")
        except Exception:
            logger.warning("Failed to write tick report", exc_info=True)


# ── helpers ────────────────────────────────────────────────────────


def _extract_price(payload: dict[str, Any]) -> float | None:
    """Extract current price from a cached spot payload row."""
    for key in ("最新价", "当前价", "收盘", "close", "price", "最新"):
        val = payload.get(key)
        if val is None or val == "" or val == "-":
            continue
        try:
            f = float(str(val).replace(",", ""))
            if f > 0:
                return round(f, 2)
        except (ValueError, TypeError):
            continue
    return None


def _portfolio_snapshot(trader: TraderAgentService) -> dict[str, Any]:
    """Compact portfolio snapshot for tick reporting."""
    p = trader.portfolio
    return {
        "cash": p.cash,
        "total_value": p.total_value,
        "total_market_value": p.total_market_value,
        "position_ratio": p.position_ratio,
        "total_pnl_pct": p.total_pnl_pct,
        "total_pnl": p.total_pnl,
        "positions": {
            sym: {
                "shares": pos.shares,
                "avg_cost": pos.avg_cost,
                "current_price": pos.current_price,
                "market_value": pos.market_value,
                "pnl_pct": pos.unrealized_pnl_pct,
            }
            for sym, pos in p.positions.items()
        },
    }
