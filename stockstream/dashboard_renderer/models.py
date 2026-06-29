"""Dashboard data models — index quotes, northbound flow, limit stats, etc."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass()
class IndexData:
    """Single index quote (上证/深证/创业板)."""

    code: str = ""              # e.g. "000001", "399001", "399006"
    name: str = ""              # e.g. "上证指数"
    close: float = 0.0          # 最新价
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    pre_close: float = 0.0      # 昨收
    change: float = 0.0         # 涨跌额
    change_pct: float = 0.0     # 涨跌幅(%)
    volume: float = 0.0         # 成交量(手)
    amount: float = 0.0         # 成交额(元)
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_akshare_row(cls, row: dict, name: str, code: str) -> IndexData:
        try:
            close = float(row.get("最新价", row.get("close", 0)))
        except (ValueError, TypeError):
            close = 0.0
        try:
            pre_close = float(row.get("昨收", row.get("pre_close", 0)))
        except (ValueError, TypeError):
            pre_close = 0.0
        try:
            change_pct = float(row.get("涨跌幅", row.get("change_pct", 0)))
        except (ValueError, TypeError):
            change_pct = 0.0
        try:
            amount = float(row.get("成交额", row.get("amount", 0)))
        except (ValueError, TypeError):
            amount = 0.0

        change = close - pre_close if close and pre_close else 0.0

        return cls(
            code=code,
            name=name,
            close=close,
            open=float(row.get("今开", row.get("open", 0)) or 0),
            high=float(row.get("最高", row.get("high", 0)) or 0),
            low=float(row.get("最低", row.get("low", 0)) or 0),
            pre_close=pre_close,
            change=change,
            change_pct=change_pct,
            amount=amount,
            volume=float(row.get("成交量", row.get("volume", 0)) or 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "close": self.close,
            "change": round(self.change, 2),
            "change_pct": round(self.change_pct, 2),
            "amount_yi": round(self.amount / 1e8, 2) if self.amount else 0,
        }


@dataclass()
class NorthboundFlow:
    """北向资金实时流向."""

    net_inflow: float = 0.0       # 北向净流入(元)
    balance: float = 0.0          # 资金余额(元)
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_akshare_row(cls, row: dict) -> NorthboundFlow:
        try:
            net_inflow = float(row.get("当日资金净流入", row.get("net_inflow", 0)))
        except (ValueError, TypeError):
            net_inflow = 0.0
        try:
            balance = float(row.get("资金余额", row.get("balance", 0)))
        except (ValueError, TypeError):
            balance = 0.0
        return cls(net_inflow=net_inflow, balance=balance)

    @property
    def net_inflow_yi(self) -> float:
        return round(self.net_inflow / 1e8, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "net_inflow": self.net_inflow,
            "net_inflow_yi": self.net_inflow_yi,
            "balance_yi": round(self.balance / 1e8, 2) if self.balance else 0,
        }


@dataclass()
class LimitStats:
    """涨跌停统计."""

    limit_up: int = 0
    limit_down: int = 0
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_akshare_row(cls, row: dict) -> LimitStats:
        try:
            limit_up = int(row.get("涨停家数", row.get("limit_up", 0)))
        except (ValueError, TypeError):
            limit_up = 0
        try:
            limit_down = int(row.get("跌停家数", row.get("limit_down", 0)))
        except (ValueError, TypeError):
            limit_down = 0
        return cls(limit_up=limit_up, limit_down=limit_down)

    def to_dict(self) -> dict[str, Any]:
        return {"limit_up": self.limit_up, "limit_down": self.limit_down}


@dataclass()
class AdvanceDeclineStats:
    """涨跌家数统计."""

    up_count: int = 0
    down_count: int = 0
    flat_count: int = 0
    total: int = 0
    up_ratio: float = 0.0
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "up_count": self.up_count,
            "down_count": self.down_count,
            "flat_count": self.flat_count,
            "total": self.total,
            "up_ratio": round(self.up_ratio, 2),
        }


@dataclass()
class HotSector:
    """热点板块."""

    name: str = ""
    code: str = ""
    change_pct: float = 0.0
    leading_stock: str = ""       # 领涨股
    leading_change: float = 0.0   # 领涨股涨跌幅

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "code": self.code,
            "change_pct": round(self.change_pct, 2),
            "leading_stock": self.leading_stock,
            "leading_change": round(self.leading_change, 2),
        }


@dataclass()
class FundFlowSummary:
    """全市场资金流向汇总."""

    main_net_inflow: float = 0.0     # 主力净流入(元)
    super_large_net: float = 0.0     # 超大单净流入
    large_net: float = 0.0           # 大单净流入
    medium_net: float = 0.0          # 中单净流入
    small_net: float = 0.0           # 小单净流入
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def main_net_yi(self) -> float:
        return round(self.main_net_inflow / 1e8, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "main_net_yi": self.main_net_yi,
            "super_large_yi": round(self.super_large_net / 1e8, 2),
            "large_yi": round(self.large_net / 1e8, 2),
            "medium_yi": round(self.medium_net / 1e8, 2),
            "small_yi": round(self.small_net / 1e8, 2),
        }


@dataclass
class DashboardData:
    """Aggregated dashboard data snapshot."""

    indices: dict[str, IndexData] = field(default_factory=dict)
    northbound: NorthboundFlow = field(default_factory=NorthboundFlow)
    limit_stats: LimitStats = field(default_factory=LimitStats)
    advance_decline: AdvanceDeclineStats = field(default_factory=AdvanceDeclineStats)
    hot_sectors: list[HotSector] = field(default_factory=list)
    fund_flow: FundFlowSummary = field(default_factory=FundFlowSummary)
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def has_data(self) -> bool:
        return bool(self.indices)

    def to_dict(self) -> dict[str, Any]:
        return {
            "indices": {k: v.to_dict() for k, v in self.indices.items()},
            "northbound": self.northbound.to_dict(),
            "limit_stats": self.limit_stats.to_dict(),
            "advance_decline": self.advance_decline.to_dict(),
            "hot_sectors": [s.to_dict() for s in self.hot_sectors[:10]],
            "fund_flow": self.fund_flow.to_dict(),
            "fetched_at": self.fetched_at.isoformat(),
        }


@dataclass()
class DashboardResult:
    """Rendered dashboard output."""

    rgba: Any = None                # numpy (1080, 1920, 4) uint8
    png_bytes: bytes = b""          # PNG binary
    render_time_ms: float = 0.0
    width: int = 1920
    height: int = 1080
    data: DashboardData = field(default_factory=DashboardData)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass()
class DashboardConfig:
    """Dashboard rendering configuration."""

    width: int = 1920
    height: int = 1080
    dpi: int = 100
    refresh_seconds: int = 10      # 每N秒刷新
    cache_dir: str = "cache/dashboard"
    # Index codes for AkShare
    index_codes: dict[str, str] = field(default_factory=lambda: {
        "sh000001": "上证指数",
        "sz399001": "深证成指",
        "sz399006": "创业板指",
    })
