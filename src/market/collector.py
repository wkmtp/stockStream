"""行情采集器。"""
from __future__ import annotations
import logging
from typing import Any
from src.market.models import MarketSnapshot

logger = logging.getLogger(__name__)


class MarketCollector:
    """行情数据采集器（AkShare / 模拟）。"""

    def __init__(self, symbols: list[str] | None = None) -> None:
        self.symbols = symbols or ["600519", "000001", "300750"]

    async def fetch_snapshot(self, symbol: str) -> MarketSnapshot | None:
        """获取单只股票快照。"""
        try:
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
        except Exception as exc:
            logger.warning("Fetch %s failed: %s", symbol, exc)
            return None

    async def fetch_all(self) -> list[MarketSnapshot]:
        """全量采集。"""
        results = []
        try:
            import akshare as ak
            df = ak.stock_zh_a_spot_em()
            for _, row in df.iterrows():
                results.append(MarketSnapshot(
                    symbol=str(row.get("代码", "")),
                    name=str(row.get("名称", "")),
                    price=float(row.get("最新价", 0)),
                    change_pct=float(row.get("涨跌幅", 0)),
                    volume=int(row.get("成交量", 0)),
                    turnover=float(row.get("成交额", 0)),
                ))
            return results
        except Exception as exc:
            logger.warning("Fetch all failed: %s", exc)
            return results
