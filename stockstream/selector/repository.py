"""Repository for reading selector inputs from the market SQLite cache."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

import aiosqlite

from stockstream.market.models import MarketDataset
from stockstream.market.storage import MarketSQLiteStorage


class SelectorMarketRepository:
    """Loads cached Eastmoney rows needed by selector rules."""

    def __init__(self, storage: MarketSQLiteStorage) -> None:
        self.storage = storage

    async def load_latest_spot(self) -> dict[str, dict[str, Any]]:
        """Load the latest realtime quote row for each symbol."""

        rows = await self._fetch_dataset_rows(MarketDataset.SPOT.value, order_desc=True)
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            symbol = row["symbol"]
            if symbol not in latest:
                latest[symbol] = row["payload"]
        return latest

    async def load_latest_fund_flow(self) -> dict[str, dict[str, Any]]:
        """Load the latest fund-flow row for each symbol."""

        rows = await self._fetch_dataset_rows(MarketDataset.FUND_FLOW.value, order_desc=True)
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            symbol = row["symbol"]
            if symbol not in latest:
                latest[symbol] = row["payload"]
        return latest

    async def load_daily_series(self) -> dict[str, list[dict[str, Any]]]:
        """Load daily K-line rows grouped by symbol and sorted from old to new."""

        rows = await self._fetch_dataset_rows(MarketDataset.DAILY.value, order_desc=False)
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[row["symbol"]].append(row["payload"])
        return dict(grouped)

    async def _fetch_dataset_rows(self, dataset: str, *, order_desc: bool) -> list[dict[str, Any]]:
        await self.storage.initialize()
        order = "DESC" if order_desc else "ASC"
        async with aiosqlite.connect(self.storage.db_path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                f"""
                SELECT symbol, trade_time, payload
                FROM market_cache
                WHERE dataset = ?
                ORDER BY symbol ASC, trade_time {order}
                """,
                (dataset,),
            )
            rows = await cursor.fetchall()
        return [
            {
                "symbol": row["symbol"],
                "trade_time": row["trade_time"],
                "payload": json.loads(row["payload"]),
            }
            for row in rows
        ]
