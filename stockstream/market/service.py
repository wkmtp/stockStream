"""Market data ingestion and AkShare collector integration.

The MarketService is the public facade for the market module. It wires together
the AkShare collector, SQLite cache storage, and the in-memory event stream.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from stockstream.core.config import get_settings
from stockstream.database.service import DatabaseService
from stockstream.market.collector import AkshareEastMoneyCollector
from stockstream.market.models import CollectorConfig, CollectorStatus
from stockstream.market.storage import MarketSQLiteStorage
from stockstream.stream.service import StreamService

logger = logging.getLogger(__name__)


class MarketService:
    """Fetches market data, runs AkShare collection, and forwards normalized ticks.

    This is the main entry point for the market module. It:
        1. Creates and manages the AkShare collector background task
        2. Exposes manual tick ingestion and refresh endpoints
        3. Provides access to the underlying SQLite storage for readers

    Usage::

        svc = MarketService(database=db, stream=stream)
        await svc.start_collector()    # begins 5-second refresh loop
        results = await svc.refresh_once()  # manual one-shot refresh
        await svc.stop_collector()     # graceful shutdown
    """

    def __init__(self, database: DatabaseService, stream: StreamService) -> None:
        self.database = database
        self.stream = stream
        settings = get_settings()
        symbols = tuple(
            s.strip() for s in settings.market_symbols.split(",") if s.strip()
        )
        self.storage = MarketSQLiteStorage(settings.market_sqlite_path)
        self.collector = AkshareEastMoneyCollector(
            storage=self.storage,
            stream=stream,
            config=CollectorConfig(
                poll_seconds=settings.market_poll_seconds,
                symbols=symbols,
            ),
        )

    # ── collector lifecycle ────────────────────────────────────────

    async def start_collector(self) -> None:
        """Start the background AkShare collector (idempotent)."""
        await self.collector.start()

    async def stop_collector(self) -> None:
        """Stop the background AkShare collector gracefully."""
        await self.collector.stop()

    @property
    def collector_status(self) -> CollectorStatus:
        """Expose collector health and reconnect state."""
        return self.collector.status

    # ── data operations ────────────────────────────────────────────

    async def refresh_once(self) -> list[dict]:
        """Run one AkShare refresh cycle and return stream-ready summaries.

        Returns:
            A list of event dicts (one per dataset collected).
        """
        results = await self.collector.refresh_once()
        return [r.to_event() for r in results]

    async def ingest_tick(self, symbol: str, price: float) -> dict:
        """Normalize and publish a single market tick onto the stream.

        Args:
            symbol: Stock code (e.g. "000001").
            price: Latest trade price.

        Returns:
            The published tick event dict.
        """
        tick = {
            "type": "market.tick",
            "symbol": symbol.upper(),
            "price": price,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        await self.stream.publish(tick)
        logger.debug("Tick ingested: %s @ %.2f", symbol, price)
        return tick
