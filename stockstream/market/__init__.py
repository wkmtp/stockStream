"""AkShare/Eastmoney market data collection module.

Public API surface:
    - MarketService       → main facade (start/stop collector, ingest ticks)
    - MarketSQLiteStorage → low-level SQLite read/write for cached market data
    - MarketDataset       → enum of supported datasets
    - CollectorConfig     → runtime tuning knobs
    - StockSymbol         → A-share code → exchange market mapping

Heavy imports (collector, storage) are intentionally deferred so that importing
market models does not require optional runtime dependencies before install.
"""

from stockstream.market.models import (
    CollectionResult,
    CollectorConfig,
    CollectorStatus,
    MarketDataset,
    StockSymbol,
)

__all__ = [
    "MarketDataset",
    "StockSymbol",
    "CollectorConfig",
    "CollectionResult",
    "CollectorStatus",
]
