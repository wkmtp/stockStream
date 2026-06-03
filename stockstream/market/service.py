"""Market data ingestion and AkShare collector integration."""

from datetime import datetime, timezone

from stockstream.core.config import get_settings
from stockstream.database.service import DatabaseService
from stockstream.market.collector import AkshareEastMoneyCollector
from stockstream.market.models import CollectorConfig
from stockstream.market.storage import MarketSQLiteStorage
from stockstream.stream.service import StreamService


class MarketService:
    """Fetches market data, runs AkShare collection, and forwards normalized ticks."""

    def __init__(self, database: DatabaseService, stream: StreamService) -> None:
        self.database = database
        self.stream = stream
        settings = get_settings()
        symbols = tuple(
            symbol.strip()
            for symbol in settings.market_symbols.split(",")
            if symbol.strip()
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

    async def ingest_tick(self, symbol: str, price: float) -> dict:
        """Normalize and publish one market tick."""

        tick = {
            "type": "market.tick",
            "symbol": symbol.upper(),
            "price": price,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        await self.stream.publish(tick)
        return tick

    async def refresh_once(self) -> list[dict]:
        """Run one AkShare refresh cycle and return stream-ready summaries."""

        results = await self.collector.refresh_once()
        return [result.to_event() for result in results]

    async def start_collector(self) -> None:
        """Start the background AkShare collector."""

        await self.collector.start()

    async def stop_collector(self) -> None:
        """Stop the background AkShare collector."""

        await self.collector.stop()
