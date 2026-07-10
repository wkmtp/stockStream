"""Chart engine data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class ChartType(str, Enum):
    """Supported chart types for the chart engine."""

    DAILY_KLINE = "daily_kline"        # 日K线图
    MINUTE60_KLINE = "minute60_kline"  # 60分钟K线图
    INTRADAY = "intraday"              # 分时图
    MACD = "macd"                      # MACD 指标
    RSI = "rsi"                        # RSI 指标
    VOLUME = "volume"                  # 成交量
    FUND_FLOW = "fund_flow"            # 资金流向

    @property
    def label(self) -> str:
        _labels = {
            ChartType.DAILY_KLINE: "日K线图",
            ChartType.MINUTE60_KLINE: "60分钟K线图",
            ChartType.INTRADAY: "分时图",
            ChartType.MACD: "MACD",
            ChartType.RSI: "RSI",
            ChartType.VOLUME: "成交量",
            ChartType.FUND_FLOW: "资金流向",
        }
        return _labels.get(self, self.value)


@dataclass
class ChartRequest:
    """Request to generate a specific chart."""

    stock_code: str
    chart_type: ChartType
    width_px: int = 1440
    height_px: int = 880
    dpi: int = 100
    force_refresh: bool = False


@dataclass
class ChartResult:
    """Result of a chart generation request."""

    stock_code: str
    chart_type: ChartType
    file_path: str            # Absolute path to cached PNG
    png_data: bytes | None = None  # Raw PNG bytes (for API responses)
    rendered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error: str | None = None
    width_px: int = 0
    height_px: int = 0

    @property
    def success(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stock_code": self.stock_code,
            "chart_type": self.chart_type.value,
            "chart_label": self.chart_type.label,
            "file_path": self.file_path,
            "rendered_at": self.rendered_at.isoformat(),
            "error": self.error,
            "width_px": self.width_px,
            "height_px": self.height_px,
            "has_data": self.png_data is not None,
        }
