"""SQLite cache storage for market data collected from AkShare."""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aiosqlite

from stockstream.core.config import get_settings
from stockstream.market.models import CollectionResult, MarketDataset


class MarketSQLiteStorage:
    """Persist normalized market rows into a small local SQLite cache."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or get_settings().market_sqlite_path or _sqlite_path_from_url(
            get_settings().db_url
        )
        self._initialized = False

    async def initialize(self) -> None:
        """Create market cache tables and indexes when they do not exist."""

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as connection:
            await connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;
                CREATE TABLE IF NOT EXISTS market_cache (
                    provider TEXT NOT NULL,
                    dataset TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    market TEXT,
                    interval TEXT NOT NULL DEFAULT '',
                    trade_time TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (provider, dataset, symbol, interval, trade_time)
                );
                CREATE INDEX IF NOT EXISTS idx_market_cache_dataset_time
                    ON market_cache(dataset, trade_time DESC);
                CREATE INDEX IF NOT EXISTS idx_market_cache_symbol_time
                    ON market_cache(symbol, trade_time DESC);
                CREATE TABLE IF NOT EXISTS market_collection_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dataset TEXT NOT NULL,
                    status TEXT NOT NULL,
                    rows INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    started_at TEXT NOT NULL,
                    ended_at TEXT NOT NULL
                );
                """
            )
            await connection.commit()
        self._initialized = True

    async def cache_dataframe(
        self,
        *,
        dataset: MarketDataset,
        dataframe: Any,
        provider: str = "eastmoney",
        symbol: str | None = None,
        market: str | None = None,
        interval: str | None = None,
        fetched_at: datetime | None = None,
    ) -> CollectionResult:
        """Cache an AkShare pandas DataFrame into SQLite using upsert semantics."""

        await self._ensure_initialized()
        fetched = fetched_at or datetime.now(timezone.utc)
        rows = _records_from_dataframe(dataframe)
        if not rows:
            await self.record_run(dataset=dataset, status="success", rows=0)
            return CollectionResult(dataset=dataset, rows=0, symbol=symbol, market=market, interval=interval)

        values = [
            (
                provider,
                dataset.value,
                _row_symbol(row, symbol),
                market or _value_as_text(row.get("市场")),
                interval or "",
                _row_trade_time(dataset, row, fetched),
                fetched.isoformat(),
                json.dumps(_sanitize(row), ensure_ascii=False, separators=(",", ":")),
            )
            for row in rows
        ]
        async with aiosqlite.connect(self.db_path) as connection:
            await connection.executemany(
                """
                INSERT INTO market_cache (
                    provider, dataset, symbol, market, interval, trade_time, fetched_at, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, dataset, symbol, interval, trade_time) DO UPDATE SET
                    market = excluded.market,
                    fetched_at = excluded.fetched_at,
                    payload = excluded.payload
                """,
                values,
            )
            await connection.commit()
        await self.record_run(dataset=dataset, status="success", rows=len(values))
        return CollectionResult(
            dataset=dataset,
            rows=len(values),
            symbol=symbol,
            market=market,
            interval=interval,
            fetched_at=fetched,
        )

    async def record_run(
        self,
        *,
        dataset: MarketDataset,
        status: str,
        rows: int = 0,
        error: str | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
    ) -> None:
        """Record collector run metadata for health inspection."""

        await self._ensure_initialized()
        started = started_at or datetime.now(timezone.utc)
        ended = ended_at or datetime.now(timezone.utc)
        async with aiosqlite.connect(self.db_path) as connection:
            await connection.execute(
                """
                INSERT INTO market_collection_runs(dataset, status, rows, error, started_at, ended_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (dataset.value, status, rows, error, started.isoformat(), ended.isoformat()),
            )
            await connection.commit()

    async def latest(self, dataset: MarketDataset, limit: int = 100) -> list[dict[str, Any]]:
        """Return the latest cached rows for a dataset."""

        await self._ensure_initialized()
        async with aiosqlite.connect(self.db_path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                """
                SELECT symbol, market, interval, trade_time, fetched_at, payload
                FROM market_cache
                WHERE dataset = ?
                ORDER BY trade_time DESC
                LIMIT ?
                """,
                (dataset.value, limit),
            )
            rows = await cursor.fetchall()
        return [dict(row) | {"payload": json.loads(row["payload"])} for row in rows]

    async def _ensure_initialized(self) -> None:
        if not self._initialized:
            await self.initialize()


def _sqlite_path_from_url(db_url: str) -> str:
    parsed = urlparse(db_url)
    if parsed.scheme.startswith("sqlite") and parsed.path:
        return parsed.path
    return os.path.join("data", "market_cache.db")


def _records_from_dataframe(dataframe: Any) -> list[dict[str, Any]]:
    if dataframe is None:
        return []
    if hasattr(dataframe, "empty") and dataframe.empty:
        return []
    if hasattr(dataframe, "to_dict"):
        return list(dataframe.to_dict(orient="records"))
    return []


def _row_symbol(row: dict[str, Any], fallback: str | None) -> str:
    value = row.get("代码") or row.get("股票代码") or row.get("symbol") or fallback or "ALL"
    return str(value).upper()


def _row_trade_time(dataset: MarketDataset, row: dict[str, Any], fetched_at: datetime) -> str:
    if dataset is MarketDataset.SPOT:
        return fetched_at.isoformat(timespec="seconds")
    value = row.get("时间") or row.get("日期") or row.get("date") or fetched_at.isoformat()
    return str(value)


def _value_as_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if hasattr(value, "item"):
        return _sanitize(value.item())
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
