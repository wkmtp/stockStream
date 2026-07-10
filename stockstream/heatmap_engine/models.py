"""Heatmap engine data models — sector snapshots, heatmap types, ranking entries."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# ── Market Dataset for sector data ────────────────────────────────────────

class MarketDataset(str, Enum):
    """Market datasets — extended with SECTOR for heatmap engine."""
    SPOT = "eastmoney_spot"
    FUND_FLOW = "eastmoney_fund_flow"
    DAILY = "eastmoney_daily"
    MINUTE_60 = "eastmoney_60m"
    SECTOR = "eastmoney_sector"  # <-- NEW: sector/industry board data


# ── Heatmap type enumeration ─────────────────────────────────────────────

class HeatmapType(str, Enum):
    """Supported heatmap/chart types for the heatmap engine."""

    HEATMAP_TILE = "heatmap_tile"              # Treemap-style sector heatmap (板块热力图)
    SECTOR_CLOUD = "sector_cloud"              # Wordcloud-style sector cloud (板块云图)
    TOP20_GAINERS = "top20_gainers"            # 涨幅排行TOP20 水平柱状图
    TOP20_FUND_FLOW = "top20_fund_flow"        # 资金流入TOP20 水平柱状图
    TOP20_VOLUME = "top20_volume"              # 成交额TOP20 水平柱状图
    COMPOSITE_DASHBOARD = "composite_dashboard"  # 综合仪表盘 (四合一)

    @property
    def label(self) -> str:
        _labels = {
            HeatmapType.HEATMAP_TILE: "板块热力图",
            HeatmapType.SECTOR_CLOUD: "板块云图",
            HeatmapType.TOP20_GAINERS: "涨幅排行TOP20",
            HeatmapType.TOP20_FUND_FLOW: "资金流入TOP20",
            HeatmapType.TOP20_VOLUME: "成交额TOP20",
            HeatmapType.COMPOSITE_DASHBOARD: "综合仪表盘",
        }
        return _labels.get(self, self.value)


# ── Sector data model ────────────────────────────────────────────────────

@dataclass
class SectorData:
    """A single sector/industry board entry from Eastmoney."""

    code: str = ""                 # 板块代码 (e.g. "BK0477")
    name: str = ""                 # 板块名称 (e.g. "半导体")
    change_pct: float = 0.0        # 涨跌幅 (%)
    price: float = 0.0             # 板块指数点位
    volume: float = 0.0            # 成交额 (元)
    fund_flow: float = 0.0         # 主力资金净流入 (元)
    turnover_rate: float = 0.0     # 换手率 (%)
    leading_stock: str = ""        # 领涨股名称
    leading_stock_code: str = ""   # 领涨股代码
    leading_stock_change: float = 0.0  # 领涨股涨跌幅
    stock_count: int = 0           # 成分股数量
    up_count: int = 0              # 上涨家数
    down_count: int = 0            # 下跌家数

    @classmethod
    def from_akshare_row(cls, row: dict) -> SectorData:
        """Build SectorData from an AkShare stock_board_industry_name_em row."""
        try:
            change = float(row.get("涨跌幅", row.get("change_pct", 0)))
        except (ValueError, TypeError):
            change = 0.0
        try:
            price = float(row.get("最新价", row.get("price", 0)))
        except (ValueError, TypeError):
            price = 0.0
        try:
            volume = float(row.get("成交额", row.get("volume", 0)))
        except (ValueError, TypeError):
            volume = 0.0
        try:
            fund_flow = float(row.get("主力净流入", row.get("main_net_inflow", 0)))
        except (ValueError, TypeError):
            fund_flow = 0.0
        try:
            turnover = float(row.get("换手率", row.get("turnover_rate", 0)))
        except (ValueError, TypeError):
            turnover = 0.0

        try:
            up_count = int(row.get("上涨家数", row.get("up_count", 0)))
        except (ValueError, TypeError):
            up_count = 0
        try:
            down_count = int(row.get("下跌家数", row.get("down_count", 0)))
        except (ValueError, TypeError):
            down_count = 0
        try:
            stock_count = int(row.get("公司家数", row.get("stock_count", 0)))
        except (ValueError, TypeError):
            stock_count = 0

        return cls(
            code=str(row.get("板块代码", row.get("code", ""))),
            name=str(row.get("板块名称", row.get("name", ""))),
            change_pct=change,
            price=price,
            volume=volume,
            fund_flow=fund_flow,
            turnover_rate=turnover,
            leading_stock=str(row.get("领涨股票名称", row.get("leading_stock", ""))),
            leading_stock_code=str(row.get("领涨股票-代码", row.get("leading_code", ""))),
            leading_stock_change=float(row.get("领涨股票-涨跌幅", row.get("leading_change", 0)) or 0),
            stock_count=stock_count,
            up_count=up_count,
            down_count=down_count,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "change_pct": self.change_pct,
            "price": self.price,
            "volume": self.volume,
            "volume_yi": round(self.volume / 1e8, 2) if self.volume else 0,
            "fund_flow": self.fund_flow,
            "fund_flow_yi": round(self.fund_flow / 1e8, 2) if self.fund_flow else 0,
            "turnover_rate": self.turnover_rate,
            "leading_stock": self.leading_stock,
            "leading_stock_code": self.leading_stock_code,
            "leading_stock_change": self.leading_stock_change,
            "stock_count": self.stock_count,
            "up_count": self.up_count,
            "down_count": self.down_count,
        }


# ── Snapshot container ────────────────────────────────────────────────────

@dataclass
class SectorSnapshot:
    """Full sector snapshot at a point in time."""

    collected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    sectors: list[SectorData] = field(default_factory=list)

    # ── Pre-computed rankings (lazy cached) ──
    _top_gainers: list[SectorData] | None = field(default=None, repr=False)
    _top_fund_flow: list[SectorData] | None = field(default=None, repr=False)
    _top_volume: list[SectorData] | None = field(default=None, repr=False)

    @property
    def count(self) -> int:
        return len(self.sectors)

    @property
    def top_gainers(self) -> list[SectorData]:
        """Top 20 sectors by change_pct (descending)."""
        if self._top_gainers is None:
            self._top_gainers = sorted(
                self.sectors, key=lambda s: s.change_pct, reverse=True
            )[:20]
        return self._top_gainers

    @property
    def top_fund_flow(self) -> list[SectorData]:
        """Top 20 sectors by main fund net inflow (descending)."""
        if self._top_fund_flow is None:
            self._top_fund_flow = sorted(
                self.sectors, key=lambda s: s.fund_flow, reverse=True
            )[:20]
        return self._top_fund_flow

    @property
    def top_volume(self) -> list[SectorData]:
        """Top 20 sectors by turnover volume (descending)."""
        if self._top_volume is None:
            self._top_volume = sorted(
                self.sectors, key=lambda s: s.volume, reverse=True
            )[:20]
        return self._top_volume

    @property
    def up_sectors(self) -> int:
        return sum(1 for s in self.sectors if s.change_pct > 0)

    @property
    def down_sectors(self) -> int:
        return sum(1 for s in self.sectors if s.change_pct < 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "collected_at": self.collected_at.isoformat(),
            "total_sectors": self.count,
            "up_sectors": self.up_sectors,
            "down_sectors": self.down_sectors,
            "top_gainers": [s.to_dict() for s in self.top_gainers],
            "top_fund_flow": [s.to_dict() for s in self.top_fund_flow],
            "top_volume": [s.to_dict() for s in self.top_volume],
        }

    def to_scene_data(self) -> list[dict]:
        """Convert to scene_manager-compatible sector_data format."""
        return [
            {
                "payload": {
                    "板块": s.name,
                    "涨跌幅": s.change_pct,
                    "成交额": s.volume,
                    "资金净流入": s.fund_flow,
                    "领涨股": s.leading_stock,
                }
            }
            for s in self.top_gainers
        ]
