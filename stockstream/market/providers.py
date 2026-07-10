"""Multi-source market data provider with AkShare → Tushare → zzshare fallback.

Each fetch method tries providers in priority order, returning the first
non-empty result. All blocking calls are delegated to worker threads via
asyncio.to_thread to keep the event loop responsive.

Mapping per dataset:
    SPOT:      AkShare(stock_zh_a_spot_em) → zzshare(rt_k) → Tushare(daily all)
    FUND_FLOW: AkShare(stock_individual_fund_flow) → Tushare(moneyflow_dc) → zzshare(stock_moneyflow)
    DAILY:     AkShare(stock_zh_a_hist) → Tushare(pro_bar fre=D) → zzshare(daily)
    MINUTE_60: AkShare(stock_zh_a_hist_min_em) → Tushare(pro_bar fre=60min) → zzshare(N/A)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

from stockstream.core.config import get_settings

logger = logging.getLogger(__name__)

import os as _os

_TUSHARE_TOKEN = _os.getenv("TUSHARE_TOKEN", _os.getenv("STOCKSTREAM_TUSHARE_TOKEN", ""))


def _to_ts_code(code: str, market: str) -> str:
    """Convert AkShare code+market to Tushare/zzshare format: '600000.SH'."""
    return f"{code.strip().upper()}.{market.strip().upper()}"


def _normalise_date(date_str: str) -> str:
    """Strip dashes/colons/spaces so the date looks like 'YYYYMMDD'."""
    return date_str.replace("-", "").replace(":", "").replace(" ", "")[:8]


def _is_non_empty_df(result: Any) -> bool:
    """Return True if *result* is a non-empty pandas DataFrame."""
    if result is None:
        return False
    try:
        return not result.empty
    except Exception:
        return bool(result)


class MarketDataProvider:
    """Multi-source market data provider with fallback chain.

    Priority: AkShare → Tushare Pro → zzshare

    Usage::

        provider = MarketDataProvider()
        df = await provider.fetch_spot()
        df = await provider.fetch_daily("000001", "sz",
                     start_date="20250101", end_date="20250601")
    """

    def __init__(self, *, tushare_token: str | None = None) -> None:
        self._tushare_token = tushare_token or _TUSHARE_TOKEN
        self._timeout: float = float(
            getattr(get_settings(), "collector_timeout_sec", 15.0)
        )

    # ── public fetch methods ───────────────────────────────────────

    async def fetch_spot(self) -> Any:
        """Fetch real-time A-share spot quotes (market-wide DataFrame or None)."""
        return await self._try_providers(
            "spot",
            [
                ("AkShare", self._akshare_spot),
                ("zzshare", self._zzshare_spot),
                ("Tushare", self._tushare_all_daily),
            ],
        )

    async def fetch_fund_flow(self, code: str, market: str) -> Any:
        """Fetch individual stock fund flow DataFrame or None."""
        label = f"fund_flow({code})"
        return await self._try_providers(
            label,
            [
                ("AkShare", lambda: self._akshare_fund_flow(code, market)),
                ("Tushare", lambda: self._tushare_fund_flow(code, market)),
                ("zzshare", lambda: self._zzshare_fund_flow(code, market)),
            ],
        )

    async def fetch_daily(
        self,
        code: str,
        market: str,
        *,
        start_date: str,
        end_date: str,
        adjust: str = "",
    ) -> Any:
        """Fetch daily K-line DataFrame or None."""
        label = f"daily({code})"
        return await self._try_providers(
            label,
            [
                (
                    "AkShare",
                    lambda: self._akshare_daily(code, start_date, end_date, adjust),
                ),
                (
                    "Tushare",
                    lambda: self._tushare_daily(code, market, start_date, end_date, adjust),
                ),
                (
                    "zzshare",
                    lambda: self._zzshare_daily(code, market, start_date, end_date, adjust),
                ),
            ],
        )

    async def fetch_60m(
        self,
        code: str,
        market: str,
        *,
        start_date: str,
        end_date: str,
        adjust: str = "",
    ) -> Any:
        """Fetch 60-minute K-line DataFrame or None."""
        label = f"60m({code})"
        return await self._try_providers(
            label,
            [
                (
                    "AkShare",
                    lambda: self._akshare_60m(code, start_date, end_date, adjust),
                ),
                (
                    "Tushare",
                    lambda: self._tushare_60m(code, market, start_date, end_date, adjust),
                ),
            ],
        )

    # ── fallback runner ────────────────────────────────────────────

    async def _try_providers(
        self, label: str, fetchers: list[tuple[str, Any]]
    ) -> Any:
        """Try each (name, callable) fetcher in order; return first non-empty DataFrame."""
        for provider_name, fetcher in fetchers:
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(fetcher), timeout=self._timeout,
                )
                if _is_non_empty_df(result):
                    logger.info(
                        "%s succeeded for %s (%d rows)",
                        provider_name, label, len(result),
                    )
                    return result
                if result is not None:
                    logger.debug(
                        "%s returned empty DataFrame for %s, trying next...",
                        provider_name, label,
                    )
                else:
                    logger.debug(
                        "%s returned None for %s, trying next...",
                        provider_name, label,
                    )
            except asyncio.TimeoutError:
                logger.warning(
                    "%s timed out for %s (%.0fs), trying next...",
                    provider_name, label, self._timeout,
                )
            except Exception as exc:
                logger.warning(
                    "%s failed for %s: %s, trying next...",
                    provider_name, label, exc,
                )
        logger.error("All providers failed for %s", label)
        return None

    # ── AkShare providers ──────────────────────────────────────────

    @staticmethod
    def _akshare_spot() -> Any:
        import akshare as ak

        return ak.stock_zh_a_spot_em()

    @staticmethod
    def _akshare_fund_flow(code: str, market: str) -> Any:
        import akshare as ak

        return ak.stock_individual_fund_flow(stock=code, market=market)

    @staticmethod
    def _akshare_daily(
        code: str, start_date: str, end_date: str, adjust: str
    ) -> Any:
        import akshare as ak

        return ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust=adjust,
        )

    @staticmethod
    def _akshare_60m(
        code: str, start_date: str, end_date: str, adjust: str
    ) -> Any:
        import akshare as ak

        return ak.stock_zh_a_hist_min_em(
            symbol=code,
            period="60",
            start_date=start_date,
            end_date=end_date,
            adjust=adjust,
        )

    # ── Tushare providers ─────────────────────────────────────────

    def _get_tushare_pro(self) -> Any:
        import tushare as ts

        ts.set_token(self._tushare_token)
        return ts.pro_api()

    def _tushare_all_daily(self) -> Any:
        """Use the daily endpoint as a spot-data approximation (all stocks on latest
        trading day returned in one call)."""
        pro = self._get_tushare_pro()
        today_str = date.today().strftime("%Y%m%d")
        df = pro.daily(trade_date=today_str)
        if _is_non_empty_df(df):
            return df
        yesterday_str = (date.today() - timedelta(days=1)).strftime("%Y%m%d")
        return pro.daily(trade_date=yesterday_str)

    def _tushare_fund_flow(self, code: str, market: str) -> Any:
        pro = self._get_tushare_pro()
        ts_code = _to_ts_code(code, market)
        return pro.moneyflow_dc(ts_code=ts_code)

    def _tushare_daily(
        self,
        code: str,
        market: str,
        start_date: str,
        end_date: str,
        adjust: str,
    ) -> Any:
        import tushare as ts

        ts_code = _to_ts_code(code, market)
        adj = None if adjust == "" else adjust
        return ts.pro_bar(
            ts_code=ts_code,
            freq="D",
            start_date=_normalise_date(start_date),
            end_date=_normalise_date(end_date),
            adj=adj,
        )

    def _tushare_60m(
        self,
        code: str,
        market: str,
        start_date: str,
        end_date: str,
        adjust: str,
    ) -> Any:
        import tushare as ts

        ts_code = _to_ts_code(code, market)
        adj = None if adjust == "" else adjust
        return ts.pro_bar(
            ts_code=ts_code,
            freq="60min",
            start_date=_normalise_date(start_date),
            end_date=_normalise_date(end_date),
            adj=adj,
        )

    # ── zzshare providers ──────────────────────────────────────────

    @staticmethod
    def _zzshare_spot() -> Any:
        """Fetch real-time spot via zzshare batch queries by market segment.

        NOTE: zzshare rt_k requires a free token from https://quant.zizizaizai.com/me/profile
        for real-time data. Without a token this will fail gracefully.
        """
        from zzshare.client import DataApi

        api = DataApi()
        dfs = []
        for ts_filter in ["6*.SH", "0*.SZ", "3*.SZ"]:  # 主板, 深市主板, 创业板
            try:
                part = api.rt_k(ts_code=ts_filter, fields="all")
                if _is_non_empty_df(part):
                    dfs.append(part)
            except Exception:
                logger.debug("zzshare rt_k batch %s failed", ts_filter)
        if not dfs:
            return None
        import pandas as pd

        return pd.concat(dfs, ignore_index=True)

    @staticmethod
    def _zzshare_fund_flow(code: str, market: str) -> Any:
        from zzshare.client import DataApi

        api = DataApi()
        return api.stock_moneyflow(stock_id=code, m_type=1)

    @staticmethod
    def _zzshare_daily(
        code: str,
        market: str,
        start_date: str,
        end_date: str,
        adjust: str,
    ) -> Any:
        from zzshare.client import DataApi

        api = DataApi()
        ts_code = _to_ts_code(code, market)
        adj = adjust or None
        return api.daily(
            ts_code=ts_code,
            start_date=_normalise_date(start_date),
            end_date=_normalise_date(end_date),
            adj=adj,
        )
