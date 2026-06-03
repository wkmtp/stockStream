"""Market module data models for AkShare/Eastmoney collection."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class MarketDataset(str, Enum):
    """Supported Eastmoney datasets collected through AkShare."""

    SPOT = "eastmoney_spot"
    FUND_FLOW = "eastmoney_fund_flow"
    DAILY = "eastmoney_daily"
    MINUTE_60 = "eastmoney_60m"


@dataclass(slots=True, frozen=True)
class StockSymbol:
    """A stock symbol plus its inferred Chinese exchange market code."""

    code: str
    market: str

    @classmethod
    def from_code(cls, code: str) -> "StockSymbol":
        """Infer AkShare market code from a six-digit A-share stock code."""

        normalized = code.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "")
        if normalized.startswith(("6", "9")):
            market = "sh"
        elif normalized.startswith(("8", "4")):
            market = "bj"
        else:
            market = "sz"
        return cls(code=normalized, market=market)


@dataclass(slots=True, frozen=True)
class CollectorConfig:
    """Runtime options for the asynchronous market collector."""

    poll_seconds: int = 5
    symbols: tuple[str, ...] = ()
    daily_start_date: str = "20200101"
    daily_end_date: str = "22220101"
    minute_start_date: str = "1979-09-01 09:32:00"
    minute_end_date: str = "2222-01-01 09:32:00"
    adjust: str = ""
    max_concurrency: int = 2
    enabled_datasets: tuple[MarketDataset, ...] = field(
        default_factory=lambda: (
            MarketDataset.SPOT,
            MarketDataset.FUND_FLOW,
            MarketDataset.DAILY,
            MarketDataset.MINUTE_60,
        )
    )


@dataclass(slots=True, frozen=True)
class CollectionResult:
    """Summary of one dataset collection run."""

    dataset: MarketDataset
    rows: int
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    symbol: str | None = None
    market: str | None = None
    interval: str | None = None

    def to_event(self) -> dict[str, Any]:
        """Convert the collection summary to a stream event."""

        return {
            "type": "market.collection",
            "dataset": self.dataset.value,
            "rows": self.rows,
            "symbol": self.symbol,
            "market": self.market,
            "interval": self.interval,
            "fetched_at": self.fetched_at.isoformat(),
        }


@dataclass(slots=True)
class CollectorStatus:
    """Mutable collector health and reconnect state."""

    running: bool = False
    reconnect_attempts: int = 0
    last_error: str | None = None
    last_success_at: datetime | None = None
