"""SQLite cache storage for market data collected from AkShare.

Persists normalized market rows into a local SQLite database with WAL mode
and upsert semantics. Designed for low memory footprint on Jetson Xavier NX.
"""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aiosqlite

from stockstream.core.config import get_settings
from stockstream.market.models import CollectionResult, MarketDataset

logger = logging.getLogger(__name__)


class MarketSQLiteStorage:
    """Persist normalized market rows into a small local SQLite cache."""

    def __init__(self, db_path: str | None = None) -> None:
        if db_path:
            self.db_path = db_path
        else:
            settings = get_settings()
            self.db_path = settings.market_sqlite_path or _sqlite_path_from_url(settings.db_url)
        self._initialized = False

    # ── lifecycle ──────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Create market cache tables and indexes when they do not exist."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as connection:
            await connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;
                PRAGMA cache_size=-8000;
                PRAGMA temp_store=MEMORY;

                CREATE TABLE IF NOT EXISTS market_cache (
                    provider     TEXT NOT NULL,
                    dataset      TEXT NOT NULL,
                    symbol       TEXT NOT NULL,
                    market       TEXT,
                    interval     TEXT NOT NULL DEFAULT '',
                    trade_time   TEXT NOT NULL,
                    fetched_at   TEXT NOT NULL,
                    payload      TEXT NOT NULL,
                    PRIMARY KEY (provider, dataset, symbol, interval, trade_time)
                );

                CREATE INDEX IF NOT EXISTS idx_market_cache_dataset_time
                    ON market_cache(dataset, trade_time DESC);

                CREATE INDEX IF NOT EXISTS idx_market_cache_symbol_time
                    ON market_cache(symbol, trade_time DESC);

                CREATE TABLE IF NOT EXISTS market_collection_runs (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    dataset    TEXT NOT NULL,
                    status     TEXT NOT NULL,
                    rows       INTEGER NOT NULL DEFAULT 0,
                    error      TEXT,
                    started_at TEXT NOT NULL,
                    ended_at   TEXT NOT NULL
                );
                """
            )
            await connection.commit()
        self._initialized = True
        logger.info("Market SQLite storage initialized at %s", self.db_path)

    async def close(self) -> None:
        """No-op close; aiosqlite connections are short-lived per operation."""
        self._initialized = False

    async def cleanup_old_data(self, keep_hours: int = 72) -> int:
        """Remove rows older than *keep_hours* to prevent unbounded growth.

        Returns number of deleted rows.
        """
        await self._ensure_initialized()
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=keep_hours)).isoformat()
        async with aiosqlite.connect(self.db_path) as connection:
            cursor = await connection.execute(
                "DELETE FROM market_cache WHERE fetched_at < ?", (cutoff,),
            )
            deleted = cursor.rowcount
            await connection.execute(
                "DELETE FROM market_collection_runs WHERE ended_at < ?", (cutoff,),
            )
            await connection.commit()
        if deleted > 0:
            logger.info("Cleaned up %d old market cache rows (cutoff=%s)", deleted, cutoff)
        return deleted

    # ── write ──────────────────────────────────────────────────────────

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
        """Cache an AkShare pandas DataFrame into SQLite using upsert semantics.

        Args:
            dataset: Which Eastmoney dataset this DataFrame belongs to.
            dataframe: A pandas DataFrame returned by an AkShare function.
            provider: Data source identifier (default "eastmoney").
            symbol: Stock code when the dataset is per-symbol.
            market: Exchange market code (sh / sz / bj).
            interval: K-line interval string (e.g. "1d", "60m").
            fetched_at: Timestamp of collection; defaults to now.

        Returns:
            A CollectionResult summarising rows written.
        """
        await self._ensure_initialized()
        fetched = fetched_at or datetime.now(timezone.utc)
        rows = _records_from_dataframe(dataframe)

        if not rows:
            await self.record_run(dataset=dataset, status="success", rows=0)
            return CollectionResult(
                dataset=dataset, rows=0,
                symbol=symbol, market=market, interval=interval,
            )

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
                    provider, dataset, symbol, market, interval,
                    trade_time, fetched_at, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, dataset, symbol, interval, trade_time)
                DO UPDATE SET
                    market     = excluded.market,
                    fetched_at = excluded.fetched_at,
                    payload    = excluded.payload
                """,
                values,
            )
            await connection.commit()

        await self.record_run(dataset=dataset, status="success", rows=len(values))
        logger.debug("Cached %d rows for dataset=%s symbol=%s", len(values), dataset.value, symbol)
        return CollectionResult(
            dataset=dataset, rows=len(values),
            symbol=symbol, market=market, interval=interval, fetched_at=fetched,
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
        started = (started_at or datetime.now(timezone.utc)).isoformat()
        ended = (ended_at or datetime.now(timezone.utc)).isoformat()
        async with aiosqlite.connect(self.db_path) as connection:
            await connection.execute(
                """
                INSERT INTO market_collection_runs
                    (dataset, status, rows, error, started_at, ended_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (dataset.value, status, rows, error, started, ended),
            )
            await connection.commit()

    # ── read ───────────────────────────────────────────────────────────

    async def latest(
        self, dataset: MarketDataset, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return the latest cached rows for a dataset, newest first."""
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
        result: list[dict[str, Any]] = []
        for row in rows:
            d = dict(row)
            try:
                d["payload"] = json.loads(row["payload"])
            except (json.JSONDecodeError, TypeError):
                d["payload"] = {}  # degrade gracefully
            result.append(d)
        return result

    async def symbol_history(
        self,
        dataset: MarketDataset,
        symbol: str,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return cached rows for a single symbol, ordered by trade_time ASC."""
        await self._ensure_initialized()
        async with aiosqlite.connect(self.db_path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                """
                SELECT symbol, market, interval, trade_time, fetched_at, payload
                FROM market_cache
                WHERE dataset = ? AND symbol = ?
                ORDER BY trade_time ASC
                LIMIT ?
                """,
                (dataset.value, symbol.upper(), limit),
            )
            rows = await cursor.fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            d = dict(row)
            try:
                d["payload"] = json.loads(row["payload"])
            except (json.JSONDecodeError, TypeError):
                d["payload"] = {}
            result.append(d)
        return result

    async def distinct_symbols(self, dataset: MarketDataset) -> list[str]:
        """Return all distinct symbols stored for a dataset."""
        await self._ensure_initialized()
        async with aiosqlite.connect(self.db_path) as connection:
            cursor = await connection.execute(
                "SELECT DISTINCT symbol FROM market_cache WHERE dataset = ? ORDER BY symbol",
                (dataset.value,),
            )
            rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def run_history(
        self, dataset: MarketDataset | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Return recent collection run records for health monitoring."""
        await self._ensure_initialized()
        async with aiosqlite.connect(self.db_path) as connection:
            connection.row_factory = aiosqlite.Row
            if dataset:
                cursor = await connection.execute(
                    """
                    SELECT * FROM market_collection_runs
                    WHERE dataset = ?
                    ORDER BY ended_at DESC LIMIT ?
                    """,
                    (dataset.value, limit),
                )
            else:
                cursor = await connection.execute(
                    "SELECT * FROM market_collection_runs ORDER BY ended_at DESC LIMIT ?",
                    (limit,),
                )
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # ── internal ───────────────────────────────────────────────────────

    async def _ensure_initialized(self) -> None:
        if not self._initialized:
            await self.initialize()


# ── helpers ────────────────────────────────────────────────────────────


def _sqlite_path_from_url(db_url: str) -> str:
    parsed = urlparse(db_url)
    if parsed.scheme.startswith("sqlite") and parsed.path:
        return parsed.path
    return os.path.join("data", "market_cache.db")


def _records_from_dataframe(dataframe: Any) -> list[dict[str, Any]]:
    """Convert a pandas DataFrame (or dict/list) into a list of row dicts."""
    if dataframe is None:
        return []
    # pandas DataFrame
    if hasattr(dataframe, "to_dict") and callable(dataframe.to_dict):
        try:
            if hasattr(dataframe, "empty") and dataframe.empty:
                return []
            return list(dataframe.to_dict(orient="records"))
        except Exception:
            return []
    # plain list of dicts
    if isinstance(dataframe, list):
        return [item if isinstance(item, dict) else {"value": item} for item in dataframe]
    # single dict
    if isinstance(dataframe, dict):
        return [dataframe]
    return []


def _row_symbol(row: dict[str, Any], fallback: str | None) -> str:
    value = row.get("代码") or row.get("股票代码") or row.get("symbol") or fallback or "ALL"
    return str(value).upper()


def _row_trade_time(
    dataset: MarketDataset, row: dict[str, Any], fetched_at: datetime
) -> str:
    if dataset is MarketDataset.SPOT:
        return fetched_at.isoformat(timespec="seconds")
    value = row.get("时间") or row.get("日期") or row.get("date") or fetched_at.isoformat()
    return str(value)


def _value_as_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _sanitize(value: Any) -> Any:
    """Recursively clean values for JSON serialization."""
    if isinstance(value, dict):
        return {str(key): _sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if hasattr(value, "item") and callable(value.item):
        return _sanitize(value.item())
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
