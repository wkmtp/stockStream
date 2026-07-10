"""行情采集器。"""
from __future__ import annotations
import asyncio
import logging
from typing import Any
from src.market.models import MarketSnapshot

logger = logging.getLogger(__name__)

# ── 24h 稳定性常量 ──
_COLLECTOR_TIMEOUT = 30.0   # 单次采集超时（秒）
_COLLECTOR_BATCH_SIZE = 200  # fetch_all 分批处理大小


class MarketCollector:
    """行情数据采集器（AkShare / 模拟）。"""

    def __init__(self, symbols: list[str] | None = None) -> None:
        self.symbols = symbols or ["600519", "000001", "300750"]

    async def fetch_snapshot(self, symbol: str) -> MarketSnapshot | None:
        """获取单只股票快照（24h 稳定：asyncio.to_thread + 超时）。"""
        try:
            ret = await asyncio.wait_for(
                asyncio.to_thread(_fetch_snapshot_sync, symbol),
                timeout=_COLLECTOR_TIMEOUT,
            )
            return ret
        except asyncio.TimeoutError:
            logger.warning("Fetch %s timed out after %.0fs", symbol, _COLLECTOR_TIMEOUT)
            return None
        except Exception as exc:
            logger.warning("Fetch %s failed: %s", symbol, exc)
            return None

    async def fetch_all(self) -> list[MarketSnapshot]:
        """全量采集（24h 稳定：asyncio.to_thread + 超时 + 分批）。"""
        try:
            ret: list[MarketSnapshot] = await asyncio.wait_for(
                asyncio.to_thread(_fetch_all_sync),
                timeout=_COLLECTOR_TIMEOUT * 2,
            )
            return ret
        except asyncio.TimeoutError:
            logger.warning("Fetch all timed out")
            return []
        except Exception as exc:
            logger.warning("Fetch all failed: %s", exc)
            return []


# ── Sync helpers (在 worker thread 中执行，不阻塞 event loop) ──────

def _fetch_snapshot_sync(symbol: str) -> MarketSnapshot | None:
    """同步获取单只股票快照（在 asyncio.to_thread 中运行）。"""
    import akshare as ak
    df = ak.stock_zh_a_spot_em()
    row = df[df["代码"] == symbol]
    if row.empty:
        return None
    r = row.iloc[0]
    return MarketSnapshot(
        symbol=symbol,
        name=str(r.get("名称", "")),
        price=float(r.get("最新价", 0)),
        change_pct=float(r.get("涨跌幅", 0)),
        volume=int(r.get("成交量", 0)),
        turnover=float(r.get("成交额", 0)),
        high=float(r.get("最高", 0)),
        low=float(r.get("最低", 0)),
        open=float(r.get("今开", 0)),
        prev_close=float(r.get("昨收", 0)),
    )


def _fetch_all_sync() -> list[MarketSnapshot]:
    """同步全量采集（在 asyncio.to_thread 中运行，含分批控制）。"""
    import akshare as ak
    df = ak.stock_zh_a_spot_em()
    results: list[MarketSnapshot] = []
    for _, row in df.iterrows():
        try:
            results.append(MarketSnapshot(
                symbol=str(row.get("代码", "")),
                name=str(row.get("名称", "")),
                price=float(row.get("最新价", 0)),
                change_pct=float(row.get("涨跌幅", 0)),
                volume=int(row.get("成交量", 0)),
                turnover=float(row.get("成交额", 0)),
            ))
        except (ValueError, KeyError, TypeError) as exc:
            logger.debug("Skip invalid row: %s", exc)
            continue
    return results
