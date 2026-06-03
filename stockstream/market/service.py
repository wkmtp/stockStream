"""Market data ingestion module."""

from datetime import datetime, timezone

from stockstream.database.service import DatabaseService
from stockstream.stream.service import StreamService


class MarketService:
    """Fetches or receives market data and forwards normalized ticks."""

    def __init__(self, database: DatabaseService, stream: StreamService) -> None:
        self.database = database
        self.stream = stream

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
