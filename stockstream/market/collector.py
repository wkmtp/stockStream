"""Async market data collector with multi-source fallback.

Implements an asyncio-based collector that fetches real-time quotes,
fund flows, daily K-lines and 60-minute K-lines from AkShare, Tushare Pro
and zzshare with automatic provider fallback. Runs on a configurable poll
interval with automatic reconnect and backoff.

Architecture:
    ┌──────────────┐     ┌──────────────────┐     ┌───────────────────────┐
    │  collector   │────▶│  asyncio.to_thread │────▶│  MarketDataProvider   │
    │  (asyncio)   │◀────│  (worker thread)   │◀────│  AkShare → Tushare    │
    └──────┬───────┘     └──────────────────┘     │  → zzshare (fallback)  │
           │                                     └───────────────────────┘
           ▼
    ┌──────────────┐     ┌──────────────────┐
    │   SQLite     │     │   Stream Bus     │
    │   (cache)    │     │   (pub/sub)      │
    └──────────────┘     └──────────────────┘
"""

from __future__ import annotations

import asyncio
import logging
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
from stockstream.market.providers import MarketDataProvider
from stockstream.market.storage import MarketSQLiteStorage
from stockstream.stream.service import StreamService

logger = logging.getLogger(__name__)


class AkshareEastMoneyCollector:
    """Collect Eastmoney data via multi-source provider (AkShare → Tushare → zzshare).

    Usage::

        storage = MarketSQLiteStorage()
        collector = AkshareEastMoneyCollector(storage=storage)
        await collector.start()       # begins background loop
        ...
        await collector.stop()        # graceful shutdown
    """

    def __init__(
        self,
        *,
        storage: MarketSQLiteStorage | None = None,
        stream: StreamService | None = None,
        config: CollectorConfig | None = None,
    ) -> None:
        settings = get_settings()
        self.config = config or CollectorConfig(
            poll_seconds=settings.market_poll_seconds,
        )
        self.storage = storage or MarketSQLiteStorage()
        self.stream = stream
        self.status = CollectorStatus()
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._semaphore = asyncio.Semaphore(self.config.max_concurrency)
        self.provider = MarketDataProvider()

    # ── lifecycle ──────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background collection loop.

        Idempotent — calling start() on an already-running collector is a no-op.
        """
        if self._task and not self._task.done():
            logger.info("Collector already running, skipping start()")
            return
        self._stop_event.clear()
        self.status.running = True
        await self.storage.initialize()
        self._task = asyncio.create_task(
            self._run_forever(), name="akshare-eastmoney-collector"
        )
        logger.info(
            "Collector started (poll=%ds, symbols=%d, datasets=%s)",
            self.config.poll_seconds,
            len(self.config.symbols),
            [d.value for d in self.config.enabled_datasets],
        )

    async def stop(self) -> None:
        """Signal the background loop to stop and wait for it to finish."""
        logger.info("Stopping collector...")
        self._stop_event.set()
        self.status.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Collector stopped")

    # ── background loop ────────────────────────────────────────────

    async def _run_forever(self) -> None:
        """Core loop: refresh → sleep → repeat, with exponential backoff on errors."""
        backoff = self.config.poll_seconds

        while not self._stop_event.is_set():
            cycle_start = datetime.now(timezone.utc)
            try:
                results = await self.refresh_once()
                self.status.reconnect_attempts = 0
                self.status.last_error = None
                self.status.last_success_at = datetime.now(timezone.utc)
                backoff = self.config.poll_seconds
                await self._publish_results(results)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                self.status.reconnect_attempts += 1
                self.status.last_error = str(exc)
                logger.warning(
                    "Collection cycle failed (attempt %d): %s",
                    self.status.reconnect_attempts, exc,
                )
                await self._record_errors(str(exc))

            # Sleep until next cycle, respecting stop_event
            elapsed = (datetime.now(timezone.utc) - cycle_start).total_seconds()
            sleep_for = max(backoff - elapsed, 0.1)
            await self._sleep_or_stop(sleep_for)
            backoff = min(backoff * 2, 60)

        self.status.running = False

    async def _sleep_or_stop(self, seconds: float) -> None:
        """Sleep for *seconds* unless stop_event is set."""
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass  # timeout means we slept the full duration → continue loop

    # ── refresh entry point ────────────────────────────────────────

    async def refresh_once(self) -> list[CollectionResult]:
        """Fetch all enabled datasets once and cache results in SQLite.

        Returns a flat list of CollectionResult summaries.
        """
        results: list[CollectionResult] = []

        # Spot data (market-wide, no per-symbol loop)
        if MarketDataset.SPOT in self.config.enabled_datasets:
            results.append(await self._collect_spot())

        # Per-symbol datasets
        if self.config.symbols:
            if MarketDataset.FUND_FLOW in self.config.enabled_datasets:
                results.extend(await self._collect_per_symbol(self._collect_fund_flow_one))
            if MarketDataset.DAILY in self.config.enabled_datasets:
                results.extend(await self._collect_per_symbol(self._collect_daily_one))
            if MarketDataset.MINUTE_60 in self.config.enabled_datasets:
                results.extend(await self._collect_per_symbol(self._collect_60m_one))

        return results

    # ── dataset collectors ─────────────────────────────────────────

    async def _collect_spot(self) -> CollectionResult:
        """Collect real-time A-share quotes (market-wide) via multi-source provider."""
        logger.debug("Collecting real-time spot data...")
        df = await self.provider.fetch_spot()
        return await self.storage.cache_dataframe(
            dataset=MarketDataset.SPOT, dataframe=df,
        )

    async def _collect_fund_flow_one(self, code: str) -> CollectionResult:
        """Collect individual stock fund flow for one symbol."""
        stock = StockSymbol.from_code(code)
        df = await self.provider.fetch_fund_flow(stock.code, stock.market)
        return await self.storage.cache_dataframe(
            dataset=MarketDataset.FUND_FLOW, dataframe=df,
            symbol=stock.code, market=stock.market,
        )

    async def _collect_daily_one(self, code: str) -> CollectionResult:
        """Collect daily K-line for one symbol."""
        stock = StockSymbol.from_code(code)
        df = await self.provider.fetch_daily(
            code=stock.code,
            market=stock.market,
            start_date=self.config.daily_start_date,
            end_date=self.config.daily_end_date,
            adjust=self.config.adjust,
        )
        return await self.storage.cache_dataframe(
            dataset=MarketDataset.DAILY, dataframe=df,
            symbol=stock.code, market=stock.market, interval="1d",
        )

    async def _collect_60m_one(self, code: str) -> CollectionResult:
        """Collect 60-minute K-line for one symbol."""
        stock = StockSymbol.from_code(code)
        df = await self.provider.fetch_60m(
            code=stock.code,
            market=stock.market,
            start_date=self.config.minute_start_date,
            end_date=self.config.minute_end_date,
            adjust=self.config.adjust,
        )
        return await self.storage.cache_dataframe(
            dataset=MarketDataset.MINUTE_60, dataframe=df,
            symbol=stock.code, market=stock.market, interval="60m",
        )

    async def _collect_per_symbol(
        self,
        collector_fn: Any,
    ) -> list[CollectionResult]:
        """Run a per-symbol collector concurrently for all configured symbols.

        Individual symbol failures are tolerated — an error result is returned
        instead of crashing the entire batch.
        """

        async def _collect_one(code: str) -> CollectionResult:
            async with self._semaphore:
                try:
                    return await collector_fn(code)
                except Exception as exc:
                    import datetime as _dt
                    logger.warning("Collector failed for symbol %s: %s", code, exc)
                    stock = StockSymbol.from_code(code)
                    return CollectionResult(
                        dataset=MarketDataset.FUND_FLOW,  # approximate
                        symbol=stock.code, market=stock.market,
                        error=str(exc),
                    )

        return await asyncio.gather(
            *(_collect_one(s) for s in self.config.symbols),
            return_exceptions=True,
        )

    # ── publish / record helpers ───────────────────────────────────

    async def _publish_results(self, results: list[CollectionResult]) -> None:
        """Publish collection results onto the stream bus if configured."""
        if not self.stream:
            return
        for result in results:
            await self.stream.publish(result.to_event())

    async def _record_errors(self, error: str) -> None:
        """Record an error status for every enabled dataset."""
        for dataset in self.config.enabled_datasets:
            await self.storage.record_run(
                dataset=dataset, status="error", error=error,
            )
