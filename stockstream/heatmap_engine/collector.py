"""Sector data collector — AkShare Eastmoney industry board fetcher.

Fetches A-share sector/industry board data from Eastmoney via AkShare,
returns a SectorSnapshot with all sector data and pre-computed rankings.

Data sources:
    - stock_board_industry_name_em()   → sector list + prices + change%
    - stock_board_industry_hist_em()   → historical sector data (for volume)
    - stock_sector_fund_flow_summary() → sector-level fund flow summary
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from stockstream.heatmap_engine.models import SectorData, SectorSnapshot

logger = logging.getLogger(__name__)


class SectorCollector:
    """Async sector data collector using AkShare Eastmoney APIs.

    Usage::

        collector = SectorCollector()
        snapshot = await collector.collect()
        print(f"{snapshot.count} sectors, top: {snapshot.top_gainers[0].name}")
    """

    # ── AkShare function names ────────────────────────────────────────

    _SECTOR_LIST_FN = "stock_board_industry_name_em"
    _SECTOR_FUND_FLOW_FN = "stock_sector_fund_flow_summary"

    def __init__(
        self,
        max_concurrency: int = 4,
        request_timeout: float = 15.0,
    ) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._timeout = request_timeout

    # ── public API ────────────────────────────────────────────────────

    async def collect(self) -> SectorSnapshot:
        """Fetch all A-share sector data and return a snapshot.

        Steps:
            1. Fetch industry board list (name, code, price, change%)
            2. Fetch sector-level fund flow summary (main net inflow)
            3. Merge into SectorData objects
            4. Return SectorSnapshot with pre-computed rankings
        """
        collected_at = datetime.now(timezone.utc)
        logger.info("Starting sector data collection...")

        # Step 1: fetch sector list
        sector_list = await self._fetch_sector_list()
        if not sector_list:
            logger.warning("Sector list fetch returned empty — returning empty snapshot")
            return SectorSnapshot(collected_at=collected_at, sectors=[])

        logger.debug("Fetched %d sectors from board list", len(sector_list))

        # Step 2: fetch fund flow summary (optional, non-blocking)
        fund_flow_map: dict[str, float] = {}
        try:
            fund_flow_map = await self._fetch_sector_fund_flow()
            logger.debug("Fetched fund flow for %d sectors", len(fund_flow_map))
        except Exception as exc:
            logger.warning("Sector fund flow fetch failed (non-critical): %s", exc)

        # Step 3: merge into SectorData
        sectors: list[SectorData] = []
        for row in sector_list:
            sd = SectorData.from_akshare_row(row)
            # Merge fund flow
            if sd.name in fund_flow_map:
                sd.fund_flow = fund_flow_map[sd.name]
            sectors.append(sd)

        logger.info(
            "Sector collection complete: %d sectors, up=%d down=%d",
            len(sectors),
            sum(1 for s in sectors if s.change_pct > 0),
            sum(1 for s in sectors if s.change_pct < 0),
        )

        return SectorSnapshot(collected_at=collected_at, sectors=sectors)

    async def collect_fast(self) -> SectorSnapshot:
        """Fast path: sector list only, no fund flow (for quick heatmap refresh)."""
        collected_at = datetime.now(timezone.utc)
        sector_list = await self._fetch_sector_list()
        sectors = [SectorData.from_akshare_row(row) for row in sector_list]
        return SectorSnapshot(collected_at=collected_at, sectors=sectors)

    # ── internal: AkShare calls ───────────────────────────────────────

    async def _fetch_sector_list(self) -> list[dict]:
        """Fetch A-share industry board list from Eastmoney."""
        df = await self._call_akshare(self._SECTOR_LIST_FN)
        return self._df_to_rows(df)

    async def _fetch_sector_fund_flow(self) -> dict[str, float]:
        """Fetch sector-level main fund net inflow summary.

        Returns a mapping of sector_name → fund_flow (yuan).
        """
        df = await self._call_akshare(self._SECTOR_FUND_FLOW_FN)
        rows = self._df_to_rows(df)
        result: dict[str, float] = {}
        for row in rows:
            name = str(row.get("名称", row.get("name", "")))
            if not name:
                continue
            try:
                net_inflow = float(row.get("主力净流入", row.get("main_net_inflow", 0)))
            except (ValueError, TypeError):
                net_inflow = 0.0
            result[name] = net_inflow
        return result

    # ── AkShare bridge ────────────────────────────────────────────────

    async def _call_akshare(self, function_name: str, **kwargs: Any) -> Any:
        """Run a blocking AkShare call in a worker thread.

        Returns None on error (caller handles gracefully).
        """

        def _call() -> Any:
            import akshare as ak
            return getattr(ak, function_name)(**kwargs)

        try:
            async with self._semaphore:
                return await asyncio.wait_for(
                    asyncio.to_thread(_call),
                    timeout=self._timeout,
                )
        except asyncio.TimeoutError:
            logger.warning("AkShare call %s timed out after %.0fs", function_name, self._timeout)
            return None
        except Exception as exc:
            logger.warning("AkShare call %s failed: %s", function_name, exc)
            return None

    # ── helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _df_to_rows(dataframe: Any) -> list[dict]:
        """Convert pandas DataFrame (or list) to list of dicts."""
        if dataframe is None:
            return []
        if hasattr(dataframe, "to_dict") and callable(dataframe.to_dict):
            try:
                if hasattr(dataframe, "empty") and dataframe.empty:
                    return []
                return list(dataframe.to_dict(orient="records"))
            except Exception:
                return []
        if isinstance(dataframe, list):
            return [item if isinstance(item, dict) else {"value": item} for item in dataframe]
        if isinstance(dataframe, dict):
            return [dataframe]
        return []
