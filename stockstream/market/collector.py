"""Async AkShare collector for Eastmoney market data."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from stockstream.core.config import get_settings
from stockstream.market.models import (
    CollectionResult,
    CollectorConfig,
    CollectorStatus,
    MarketDataset,
    StockSymbol,
)
from stockstream.market.storage import MarketSQLiteStorage
from stockstream.stream.service import StreamService


class AkshareEastMoneyCollector:
    """Collect Eastmoney data via AkShare with asyncio scheduling and reconnects."""

    def __init__(
        self,
        *,
        storage: MarketSQLiteStorage | None = None,
        stream: StreamService | None = None,
        config: CollectorConfig | None = None,
    ) -> None:
        settings = get_settings()
        self.config = config or CollectorConfig(poll_seconds=settings.market_poll_seconds)
        self.storage = storage or MarketSQLiteStorage()
        self.stream = stream
        self.status = CollectorStatus()
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._semaphore = asyncio.Semaphore(self.config.max_concurrency)

    async def start(self) -> None:
        """Start a background loop that refreshes data every configured interval."""

        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self.status.running = True
        self._task = asyncio.create_task(self.run_forever(), name="akshare-eastmoney-collector")

    async def stop(self) -> None:
        """Stop the background collector loop."""

        self._stop_event.set()
        self.status.running = False
        if self._task:
            await self._task

    async def run_forever(self) -> None:
        """Refresh market data every five seconds and reconnect after failures."""

        backoff_seconds = self.config.poll_seconds
        await self.storage.initialize()
        while not self._stop_event.is_set():
            started = datetime.now(timezone.utc)
            try:
                results = await self.refresh_once()
                self.status.reconnect_attempts = 0
                self.status.last_error = None
                self.status.last_success_at = datetime.now(timezone.utc)
                backoff_seconds = self.config.poll_seconds
                await self._publish_results(results)
                elapsed = (datetime.now(timezone.utc) - started).total_seconds()
                await self._sleep_until_next_cycle(max(self.config.poll_seconds - elapsed, 0))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.status.reconnect_attempts += 1
                self.status.last_error = str(exc)
                await self._record_dataset_errors(str(exc))
                await self._sleep_until_next_cycle(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, 60)
        self.status.running = False

    async def refresh_once(self) -> list[CollectionResult]:
        """Fetch enabled datasets once and cache all returned rows in SQLite."""

        results: list[CollectionResult] = []
        if MarketDataset.SPOT in self.config.enabled_datasets:
            results.append(await self.collect_spot())
        if MarketDataset.FUND_FLOW in self.config.enabled_datasets:
            results.extend(await self.collect_fund_flow())
        if MarketDataset.DAILY in self.config.enabled_datasets:
            results.extend(await self.collect_daily())
        if MarketDataset.MINUTE_60 in self.config.enabled_datasets:
            results.extend(await self.collect_60m())
        return results

    async def collect_spot(self) -> CollectionResult:
        """Collect Eastmoney realtime A-share quotes."""

        dataframe = await self._call_akshare("stock_zh_a_spot_em")
        return await self.storage.cache_dataframe(dataset=MarketDataset.SPOT, dataframe=dataframe)

    async def collect_fund_flow(self) -> list[CollectionResult]:
        """Collect Eastmoney individual stock fund-flow data for configured symbols."""

        async def collect_one(symbol_code: str) -> CollectionResult:
            stock = StockSymbol.from_code(symbol_code)
            async with self._semaphore:
                dataframe = await self._call_akshare(
                    "stock_individual_fund_flow",
                    stock=stock.code,
                    market=stock.market,
                )
            return await self.storage.cache_dataframe(
                dataset=MarketDataset.FUND_FLOW,
                dataframe=dataframe,
                symbol=stock.code,
                market=stock.market,
            )

        return await asyncio.gather(*(collect_one(symbol) for symbol in self.config.symbols))

    async def collect_daily(self) -> list[CollectionResult]:
        """Collect Eastmoney daily K-line data for configured symbols."""

        async def collect_one(symbol_code: str) -> CollectionResult:
            stock = StockSymbol.from_code(symbol_code)
            async with self._semaphore:
                dataframe = await self._call_akshare(
                    "stock_zh_a_hist",
                    symbol=stock.code,
                    period="daily",
                    start_date=self.config.daily_start_date,
                    end_date=self.config.daily_end_date,
                    adjust=self.config.adjust,
                )
            return await self.storage.cache_dataframe(
                dataset=MarketDataset.DAILY,
                dataframe=dataframe,
                symbol=stock.code,
                market=stock.market,
                interval="1d",
            )

        return await asyncio.gather(*(collect_one(symbol) for symbol in self.config.symbols))

    async def collect_60m(self) -> list[CollectionResult]:
        """Collect Eastmoney 60-minute K-line data for configured symbols."""

        async def collect_one(symbol_code: str) -> CollectionResult:
            stock = StockSymbol.from_code(symbol_code)
            async with self._semaphore:
                dataframe = await self._call_akshare(
                    "stock_zh_a_hist_min_em",
                    symbol=stock.code,
                    start_date=self.config.minute_start_date,
                    end_date=self.config.minute_end_date,
                    period="60",
                    adjust=self.config.adjust,
                )
            return await self.storage.cache_dataframe(
                dataset=MarketDataset.MINUTE_60,
                dataframe=dataframe,
                symbol=stock.code,
                market=stock.market,
                interval="60m",
            )

        return await asyncio.gather(*(collect_one(symbol) for symbol in self.config.symbols))

    async def _call_akshare(self, function_name: str, **kwargs: Any) -> Any:
        """Run a blocking AkShare call in a worker thread."""

        def call() -> Any:
            import akshare as ak

            return getattr(ak, function_name)(**kwargs)

        return await asyncio.to_thread(call)

    async def _publish_results(self, results: list[CollectionResult]) -> None:
        if not self.stream:
            return
        for result in results:
            await self.stream.publish(result.to_event())

    async def _record_dataset_errors(self, error: str) -> None:
        for dataset in self.config.enabled_datasets:
            await self.storage.record_run(dataset=dataset, status="error", error=error)

    async def _sleep_until_next_cycle(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            return
