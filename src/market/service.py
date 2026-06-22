"""行情服务 — 通过事件总线与其他模块通讯。"""
from __future__ import annotations
import asyncio
import logging
from src.core.event_bus import EventBus, get_event_bus
from src.market.collector import MarketCollector
from src.market.models import MarketSnapshot
from src.storage.service import StorageService

logger = logging.getLogger(__name__)


class MarketService:
    """行情数据服务。

    推送事件:
      market.price_updated  — 单股价格更新
      market.batch_updated  — 批量行情更新
    """

    def __init__(
        self,
        collector: MarketCollector | None = None,
        storage: StorageService | None = None,
        bus: EventBus | None = None,
    ) -> None:
        self.collector = collector or MarketCollector()
        self.storage = storage
        self._bus: EventBus | None = bus
        self._task: asyncio.Task | None = None
        self._running = False
        self._poll_seconds = 5.0

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    async def start(self, poll_seconds: float = 5.0) -> None:
        self._poll_seconds = poll_seconds
        self._running = True
        bus = await self.bus
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("MarketService started (poll=%ss)", poll_seconds)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("MarketService stopped")

    async def _poll_loop(self) -> None:
        bus = await self.bus
        while self._running:
            try:
                snapshots = await self.collector.fetch_all()
                if snapshots:
                    await bus.emit_async("market.batch_updated", {
                        "count": len(snapshots),
                        "snapshots": [s.to_dict() for s in snapshots[:20]],
                    })
                    # 持久化
                    if self.storage:
                        for s in snapshots[:20]:
                            await self.storage.stocks.insert_price(
                                s.symbol, s.price, s.volume,
                            )
            except Exception as exc:
                logger.error("Market poll error: %s", exc)
            await asyncio.sleep(self._poll_seconds)

    async def get_snapshot(self, symbol: str) -> dict | None:
        snap = await self.collector.fetch_snapshot(symbol)
        return snap.to_dict() if snap else None
