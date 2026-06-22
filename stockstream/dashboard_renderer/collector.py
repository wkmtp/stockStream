"""Dashboard data collector — fetches index, northbound, limit, advance/decline,
hot sector and fund flow data via AkShare (thread-pooled async).

Data sources (all via AkShare):
    - 上证/深证/创业板: stock_zh_index_daily_em  /  index_zh_a_hist
    - 北向资金:       stock_hsgt_north_net_flow_in_em
    - 涨跌停统计:     stock_zt_pool_em / stock_zt_pool_dtgc_em
    - 涨跌家数:       从 spot 全市场数据聚合
    - 热点板块:       stock_board_industry_name_em
    - 资金流向:       stock_sector_fund_flow_summary → 聚合全市场
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from stockstream.dashboard_renderer.models import (
    AdvanceDeclineStats,
    DashboardData,
    FundFlowSummary,
    HotSector,
    IndexData,
    LimitStats,
    NorthboundFlow,
)
from stockstream.market.storage import MarketSQLiteStorage

logger = logging.getLogger(__name__)


class DashboardCollector:
    """Async collector for all dashboard data panels."""

    def __init__(
        self,
        storage: MarketSQLiteStorage | None = None,
        concurrency: int = 3,
    ) -> None:
        self.storage = storage or MarketSQLiteStorage()
        self._semaphore = asyncio.Semaphore(concurrency)

    # ── Public entry ──────────────────────────────────────────────

    async def collect_all(self) -> DashboardData:
        """Fetch all dashboard panels concurrently, return aggregated DashboardData.

        Individual panel failures are tolerated — the returned DashboardData
        will have empty/zero fields for failed panels.
        """
        indices_task = asyncio.create_task(self._collect_indices())
        northbound_task = asyncio.create_task(self._collect_northbound())
        limit_task = asyncio.create_task(self._collect_limit_stats())
        ad_task = asyncio.create_task(self._collect_advance_decline())
        sectors_task = asyncio.create_task(self._collect_hot_sectors())
        fund_flow_task = asyncio.create_task(self._collect_fund_flow())

        results = await asyncio.gather(
            indices_task, northbound_task, limit_task,
            ad_task, sectors_task, fund_flow_task,
            return_exceptions=True,
        )

        indices = _unwrap(results[0], {})
        northbound = _unwrap(results[1], NorthboundFlow())
        limit_stats = _unwrap(results[2], LimitStats())
        advance_decline = _unwrap(results[3], AdvanceDeclineStats())
        hot_sectors = _unwrap(results[4], [])
        fund_flow = _unwrap(results[5], FundFlowSummary())

        return DashboardData(
            indices=indices,
            northbound=northbound,
            limit_stats=limit_stats,
            advance_decline=advance_decline,
            hot_sectors=hot_sectors,
            fund_flow=fund_flow,
        )

    # ── Individual collectors ─────────────────────────────────────

    async def _collect_indices(self) -> dict[str, IndexData]:
        """Collect 上证/深证/创业板 real-time quotes."""
        async with self._semaphore:
            try:
                df = await self._call_akshare("stock_zh_index_spot_em")
                if df is None or df.empty:
                    return {}

                result: dict[str, IndexData] = {}
                name_to_code = {
                    "上证指数": "000001",
                    "深证成指": "399001",
                    "创业板指": "399006",
                }
                for _, row in df.iterrows():
                    name = str(row.get("名称", row.get("name", "")))
                    if name in name_to_code:
                        code = name_to_code[name]
                        result[name] = IndexData.from_akshare_row(row, name, code)
                        logger.debug("Index %s: %.2f (%+.2f%%)", name,
                                     result[name].close, result[name].change_pct)
                return result
            except Exception as exc:
                logger.warning("Index collection failed: %s", exc)
                return {}

    async def _collect_northbound(self) -> NorthboundFlow:
        """Collect 北向资金净流入."""
        async with self._semaphore:
            try:
                df = await self._call_akshare("stock_hsgt_north_net_flow_in_em")
                if df is None or df.empty:
                    return NorthboundFlow()
                row = df.iloc[-1]  # latest row
                return NorthboundFlow.from_akshare_row(row)
            except Exception as exc:
                logger.warning("Northbound collection failed: %s", exc)
                return NorthboundFlow()

    async def _collect_limit_stats(self) -> LimitStats:
        """Collect 涨停/跌停 家数 from limit-up pool."""
        async with self._semaphore:
            try:
                # Use the limit-up pool EM API
                df_up = await self._call_akshare("stock_zt_pool_em")
                df_down = await self._call_akshare("stock_zt_pool_dtgc_em")
                limit_up = len(df_up) if df_up is not None and not df_up.empty else 0
                limit_down = len(df_down) if df_down is not None and not df_down.empty else 0
                return LimitStats(limit_up=limit_up, limit_down=limit_down)
            except Exception as exc:
                logger.warning("Limit stats collection failed: %s", exc)
                return LimitStats()

    async def _collect_advance_decline(self) -> AdvanceDeclineStats:
        """Aggregate advance/decline from spot market data in SQLite cache."""
        try:
            from stockstream.market.models import MarketDataset
            rows = await self.storage.latest(MarketDataset.SPOT, limit=5000)
            if not rows:
                return AdvanceDeclineStats()

            up = down = flat = 0
            for row in rows:
                payload = row.get("payload", {})
                pct = _safe_float(payload, "涨跌幅")
                if pct is None:
                    flat += 1
                elif pct > 0:
                    up += 1
                elif pct < 0:
                    down += 1
                else:
                    flat += 1

            total = up + down + flat
            up_ratio = (up / total * 100) if total > 0 else 0.0
            return AdvanceDeclineStats(
                up_count=up, down_count=down, flat_count=flat,
                total=total, up_ratio=up_ratio,
            )
        except Exception as exc:
            logger.warning("Advance/decline collection failed: %s", exc)
            return AdvanceDeclineStats()

    async def _collect_hot_sectors(self) -> list[HotSector]:
        """Collect top 10 hot sectors by change%."""
        async with self._semaphore:
            try:
                df = await self._call_akshare("stock_board_industry_name_em")
                if df is None or df.empty:
                    return []

                sectors: list[HotSector] = []
                for _, row in df.iterrows():
                    name = str(row.get("板块名称", row.get("name", "")))
                    code = str(row.get("板块代码", row.get("code", "")))
                    change_pct = _safe_float(row, "涨跌幅")
                    leading_stock = str(row.get("领涨股票名称", row.get("leading_stock", "")))
                    leading_change = _safe_float(row, "领涨股票-涨跌幅")

                    if change_pct is None:
                        continue
                    sectors.append(HotSector(
                        name=name, code=code,
                        change_pct=change_pct,
                        leading_stock=leading_stock,
                        leading_change=leading_change or 0.0,
                    ))

                # Sort by abs(change%) descending, take top 10
                sectors.sort(key=lambda s: abs(s.change_pct), reverse=True)
                return sectors[:10]
            except Exception as exc:
                logger.warning("Hot sectors collection failed: %s", exc)
                return []

    async def _collect_fund_flow(self) -> FundFlowSummary:
        """Collect market-wide fund flow summary from sector fund flow API."""
        async with self._semaphore:
            try:
                df = await self._call_akshare("stock_sector_fund_flow_summary",
                                              sector="市场总貌", indicator="今日")
                if df is None or df.empty:
                    return FundFlowSummary()

                row = df.iloc[0] if not df.empty else {}
                return FundFlowSummary(
                    main_net_inflow=_safe_float(row, "主力净流入-净额") or 0,
                    super_large_net=_safe_float(row, "超大单净流入-净额") or 0,
                    large_net=_safe_float(row, "大单净流入-净额") or 0,
                    medium_net=_safe_float(row, "中单净流入-净额") or 0,
                    small_net=_safe_float(row, "小单净流入-净额") or 0,
                )
            except Exception as exc:
                logger.warning("Fund flow collection failed: %s", exc)
                return FundFlowSummary()

    # ── AkShare bridge ────────────────────────────────────────────

    async def _call_akshare(self, function_name: str, **kwargs: Any) -> Any:
        """Run a blocking AkShare call in a worker thread.

        Wraps the blocking call with a hard timeout (default 15 s) to prevent
        a hung network request from blocking the dashboard refresh loop.
        """

        def _call() -> Any:
            import akshare as ak
            return getattr(ak, function_name)(**kwargs)

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(_call),
                timeout=15.0,
            )
        except asyncio.TimeoutError:
            logger.debug("AkShare call %s timed out after 15s", function_name)
            return None
        except Exception as exc:
            logger.debug("AkShare call %s failed: %s", function_name, exc)
            return None


# ── helpers ──────────────────────────────────────────────────────────────

def _safe_float(row: Any, key: str) -> float | None:
    """Safely extract a float from a row (dict/Series)."""
    val = None
    try:
        val = row.get(key)
    except Exception:
        return None
    if val in (None, "", "-", "nan"):
        return None
    try:
        if isinstance(val, str):
            val = val.replace(",", "").replace("%", "")
        return float(val)
    except (ValueError, TypeError):
        return None


def _unwrap(result: Any, default: Any) -> Any:
    """Unwrap asyncio.gather result, returning default on exception."""
    if isinstance(result, BaseException):
        return default
    return result
