"""Analysis module data models — query types, contexts, and results."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AnalysisType(str, Enum):
    """Supported analysis input types."""

    STOCK = "stock"          # 个股分析：股票名或股票代码
    SECTOR = "sector"        # 板块分析：板块名称
    MARKET = "market"        # 大盘分析


class AnalysisEngine(str, Enum):
    """Backend engine used to generate the commentary."""

    RULES = "rules"          # 规则引擎（纯本地）
    DEEPSEEK = "deepseek"    # DeepSeek 云 API（LLM）


@dataclass(slots=True, frozen=True)
class StockContext:
    """Technical + fund-flow context for a single stock."""

    symbol: str
    name: str = ""
    close: float | None = None
    change_pct: float | None = None
    ma20: float | None = None
    ma60: float | None = None
    ma20_deviation_pct: float | None = None
    macd_diff: float | None = None
    macd_signal: float | None = None
    macd_golden_cross: bool = False
    macd_dead_cross: bool = False
    rsi14: float | None = None
    turnover_pct: float | None = None
    main_inflow: float | None = None         # 主力净流入（万元）
    main_inflow_pct: float | None = None     # 主力净流入占比
    super_large_inflow: float | None = None  # 超大单净流入
    large_inflow: float | None = None        # 大单净流入
    shrinking_volume: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "close": self.close,
            "change_pct": self.change_pct,
            "ma20": self.ma20,
            "ma60": self.ma60,
            "ma20_deviation_pct": self.ma20_deviation_pct,
            "macd_diff": self.macd_diff,
            "macd_signal": self.macd_signal,
            "macd_golden_cross": self.macd_golden_cross,
            "macd_dead_cross": self.macd_dead_cross,
            "rsi14": self.rsi14,
            "turnover_pct": self.turnover_pct,
            "main_inflow": self.main_inflow,
            "main_inflow_pct": self.main_inflow_pct,
            "super_large_inflow": self.super_large_inflow,
            "large_inflow": self.large_inflow,
            "shrinking_volume": self.shrinking_volume,
        }


@dataclass(slots=True, frozen=True)
class MarketContext:
    """Aggregate market overview context."""

    up_count: int = 0
    down_count: int = 0
    flat_count: int = 0
    avg_change_pct: float | None = None
    total_turnover: float | None = None       # 亿
    top_sectors: tuple[str, ...] = ()          # 领涨板块
    bottom_sectors: tuple[str, ...] = ()       # 领跌板块
    main_inflow_total: float | None = None     # 主力净流入总额
    hotspot_summary: str = ""                  # 热点一句话总结

    def to_dict(self) -> dict[str, Any]:
        return {
            "up_count": self.up_count,
            "down_count": self.down_count,
            "flat_count": self.flat_count,
            "avg_change_pct": self.avg_change_pct,
            "total_turnover": self.total_turnover,
            "top_sectors": list(self.top_sectors),
            "bottom_sectors": list(self.bottom_sectors),
            "main_inflow_total": self.main_inflow_total,
            "hotspot_summary": self.hotspot_summary,
        }


@dataclass(slots=True, frozen=True)
class SectorContext:
    """Aggregate sector analysis context."""

    name: str
    change_pct: float | None = None
    up_count: int = 0
    down_count: int = 0
    main_inflow: float | None = None           # 板块主力净流入
    leading_stocks: tuple[str, ...] = ()       # 领涨个股
    lagging_stocks: tuple[str, ...] = ()       # 领跌个股
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "change_pct": self.change_pct,
            "up_count": self.up_count,
            "down_count": self.down_count,
            "main_inflow": self.main_inflow,
            "leading_stocks": list(self.leading_stocks),
            "lagging_stocks": list(self.lagging_stocks),
            "summary": self.summary,
        }


@dataclass(slots=True, frozen=True)
class AnalysisResult:
    """Unified analysis result returned to callers."""

    analysis_type: AnalysisType
    engine: AnalysisEngine
    script: str                            # 200字以内主播口播文案
    query: str                             # 原始输入
    context: dict[str, Any] = field(default_factory=dict)
    token_count: int = 0                   # LLM token 用量（规则引擎为 0）

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_type": self.analysis_type.value,
            "engine": self.engine.value,
            "script": self.script,
            "query": self.query,
            "context": self.context,
            "token_count": self.token_count,
        }
