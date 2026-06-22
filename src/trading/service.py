"""交易执行服务。"""
from __future__ import annotations
import logging
from src.core.event_bus import EventBus, get_event_bus
from src.trading.models import Portfolio, Transaction
from src.storage.service import StorageService

logger = logging.getLogger(__name__)


class TradingService:
    """交易执行服务。

    推送事件:
      trading.order    — 下单
      trading.filled   — 成交
    """

    def __init__(
        self,
        portfolio: Portfolio | None = None,
        storage: StorageService | None = None,
        bus: EventBus | None = None,
    ) -> None:
        self.portfolio = portfolio or Portfolio()
        self.storage = storage
        self._bus: EventBus | None = bus

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    async def buy(self, symbol: str, quantity: int, price: float,
                  reason: str = "") -> Transaction:
        txn = Transaction(symbol=symbol, action="buy", quantity=quantity,
                          price=price, reason=reason)
        # 更新持仓
        if symbol in self.portfolio.positions:
            pos = self.portfolio.positions[symbol]
            total_qty = pos.quantity + quantity
            pos.avg_cost = (pos.total_cost + txn.amount) / total_qty
            pos.quantity = total_qty
        else:
            self.portfolio.positions[symbol] = Position(
                symbol=symbol, quantity=quantity, avg_cost=price,
            )
        self.portfolio.cash -= txn.amount
        self.portfolio.transactions.append(txn)

        # 持久化 + 事件
        if self.storage:
            await self.storage.trades.record_trade(
                symbol, "buy", quantity, price, reason=reason,
            )
        bus = await self.bus
        await bus.emit_async("trading.filled", txn.to_dict(), source="trading")
        return txn

    async def sell(self, symbol: str, quantity: int, price: float,
                   reason: str = "") -> Transaction | None:
        if symbol not in self.portfolio.positions:
            return None
        pos = self.portfolio.positions[symbol]
        qty = min(quantity, pos.quantity)
        txn = Transaction(symbol=symbol, action="sell", quantity=qty,
                          price=price, reason=reason)
        pos.quantity -= qty
        self.portfolio.cash += txn.amount
        if pos.quantity <= 0:
            del self.portfolio.positions[symbol]
        self.portfolio.transactions.append(txn)

        if self.storage:
            await self.storage.trades.record_trade(
                symbol, "sell", qty, price, reason=reason,
            )
        bus = await self.bus
        await bus.emit_async("trading.filled", txn.to_dict(), source="trading")
        return txn
