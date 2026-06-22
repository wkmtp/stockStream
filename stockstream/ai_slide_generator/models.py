"""AI Slide Generator data models — slide types, templates, and result containers.

Each slide type maps to a stock selection signal category:
    OPEN  → 建仓推荐 slide
    ADD   → 补仓推荐 slide
    REDUCE → 减仓提示 slide
    CLEAR → 清仓提示 slide
    + standalone 风险提示 slide
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np


# ── Slide type enumeration ──────────────────────────────────────────────

class SlideType(str, Enum):
    """Financial PPT slide types mapped to selector signals."""

    OPEN_POSITION = "open_position"     # 建仓推荐
    ADD_POSITION = "add_position"        # 补仓推荐
    REDUCE_POSITION = "reduce_position"  # 减仓提示
    CLEAR_POSITION = "clear_position"    # 清仓提示
    RISK_WARNING = "risk_warning"        # 风险提示 (standalone)

    @property
    def label(self) -> str:
        _labels = {
            SlideType.OPEN_POSITION: "建仓推荐",
            SlideType.ADD_POSITION: "补仓推荐",
            SlideType.REDUCE_POSITION: "减仓提示",
            SlideType.CLEAR_POSITION: "清仓提示",
            SlideType.RISK_WARNING: "风险提示",
        }
        return _labels.get(self, self.value)

    @property
    def icon(self) -> str:
        _icons = {
            SlideType.OPEN_POSITION: "▲",
            SlideType.ADD_POSITION: "▲",
            SlideType.REDUCE_POSITION: "▼",
            SlideType.CLEAR_POSITION: "▼",
            SlideType.RISK_WARNING: "⚠",
        }
        return _icons.get(self, "●")

    @classmethod
    def from_signal_type(cls, signal: str) -> SlideType:
        _map = {
            "open_position": cls.OPEN_POSITION,
            "add_position": cls.ADD_POSITION,
            "reduce_position": cls.REDUCE_POSITION,
            "clear_position": cls.CLEAR_POSITION,
        }
        return _map.get(signal, cls.RISK_WARNING)


# ── Slide configuration ─────────────────────────────────────────────────

@dataclass(slots=True)
class SlideConfig:
    """Rendering configuration for one slide page.

    Designed to render at 1920×1080 for seamless integration with
    the layout engine's chart/scene area.
    """

    # ── canvas ──
    width: int = 1920
    height: int = 1080
    dpi: int = 100

    # ── margins ──
    margin_left: int = 80
    margin_right: int = 80
    margin_top: int = 70
    margin_bottom: int = 60

    # ── fonts ──
    title_font_size: int = 44
    subtitle_font_size: int = 28
    body_font_size: int = 24
    small_font_size: int = 18
    table_font_size: int = 22
    stock_code_font_size: int = 32

    # ── colors (overridable) ──
    bg_primary: str = "#0D1117"
    bg_card: str = "#161B22"
    bg_header: str = "#1C2333"
    accent_green: str = "#3FB950"
    accent_red: str = "#F85149"
    accent_blue: str = "#58A6FF"
    accent_orange: str = "#D29922"
    accent_purple: str = "#A371F7"
    accent_cyan: str = "#39D2C0"
    text_primary: str = "#E6EDF3"
    text_secondary: str = "#8B949E"
    text_tertiary: str = "#484F58"
    border: str = "#30363D"
    border_highlight: str = "#58A6FF"
    divider: str = "#21262D"

    # ── layout ──
    header_height: int = 140
    card_padding: int = 32
    card_gap: int = 24
    card_radius: int = 16
    max_cards_per_slide: int = 3
    reason_tag_padding: int = 12
    reason_tag_gap: int = 10
    table_row_height: int = 56

    @property
    def content_width(self) -> int:
        return self.width - self.margin_left - self.margin_right

    @property
    def content_height(self) -> int:
        return self.height - self.margin_top - self.margin_bottom

    @property
    def content_area(self) -> tuple[int, int]:
        return (self.content_width, self.content_height)


# ── Slide data per stock ────────────────────────────────────────────────

@dataclass(slots=True)
class StockSlideCard:
    """Data for one stock card on a slide."""

    symbol: str
    name: str
    close: float | None = None
    ma20: float | None = None
    ma20_deviation_pct: float | None = None
    daily_change_pct: float | None = None
    turnover_pct: float | None = None
    money_flow: float | None = None
    institutional_money_flow: float | None = None
    rsi14: float | None = None
    reasons: tuple[str, ...] = field(default_factory=tuple)
    rank: int = 1  # ranking within the slide (1-based)

    @property
    def is_positive(self) -> bool:
        return (self.daily_change_pct or 0) >= 0


# ── Slide data container ────────────────────────────────────────────────

@dataclass
class SlideData:
    """Complete data for rendering one PPT-style slide page."""

    slide_type: SlideType = SlideType.RISK_WARNING
    title: str = ""
    subtitle: str = ""
    cards: list[StockSlideCard] = field(default_factory=list)
    risk_text: str = ""
    disclaimer: str = "以上内容由 AI 生成，仅供参考，不构成投资建议 | 投资有风险，入市需谨慎"
    generated_at: str = ""  # ISO timestamp

    # Optional: pre-built stats for header
    market_summary: str = ""  # e.g. "全市场评估 2860 只，筛选出 Top10"
    extra_note: str = ""      # e.g. "数据刷新于 14:35:00"

    def to_dict(self) -> dict:
        return {
            "slide_type": self.slide_type.value,
            "title": self.title,
            "subtitle": self.subtitle,
            "card_count": len(self.cards),
            "cards": [
                {
                    "symbol": c.symbol,
                    "name": c.name,
                    "close": c.close,
                    "daily_change_pct": c.daily_change_pct,
                    "reasons": list(c.reasons),
                    "rank": c.rank,
                }
                for c in self.cards
            ],
            "risk_text": self.risk_text,
            "generated_at": self.generated_at,
        }


# ── Slide result (rendered PNG) ─────────────────────────────────────────

@dataclass
class SlideResult:
    """Result of rendering one slide: a PNG RGBA numpy array plus metadata."""

    slide_type: SlideType
    title: str
    rgba: np.ndarray       # uint8 RGBA (H, W, 4)
    png_bytes: bytes = field(default=b"")
    width: int = 1920
    height: int = 1080
    card_count: int = 0
    generated_at: str = ""
    render_time_ms: float = 0.0

    def to_png_file(self, path: str) -> None:
        """Save the slide as a PNG file."""
        from PIL import Image
        img = Image.fromarray(self.rgba, mode="RGBA")
        img.save(path, format="PNG")


# ── Slide template (layout preset) ──────────────────────────────────────

@dataclass
class SlideTemplate:
    """Pre-defined template for a slide type with colour and layout hints."""

    slide_type: SlideType
    title_prefix: str          # e.g. "📈 建仓推荐"
    title_color: str           # accent colour for title
    header_bg: str             # header background gradient start
    card_border_color: str     # card left border accent
    badge_color: str           # rank badge colour
    reason_bg: str             # reason tag background
    reason_text_color: str     # reason tag text
    show_score: bool = False   # show sort_amount in card
    show_table: bool = False   # show tabular layout instead of cards


# ── Named presets for easy access ───────────────────────────────────────

OpenPositionSlide = SlideTemplate(
    slide_type=SlideType.OPEN_POSITION,
    title_prefix="📈 建仓推荐",
    title_color="#3FB950",
    header_bg="#0D3320",
    card_border_color="#3FB950",
    badge_color="#3FB950",
    reason_bg="#0D3320",
    reason_text_color="#7EE787",
    show_score=True,
)

AddPositionSlide = SlideTemplate(
    slide_type=SlideType.ADD_POSITION,
    title_prefix="🔵 补仓推荐",
    title_color="#58A6FF",
    header_bg="#0D1F3C",
    card_border_color="#58A6FF",
    badge_color="#58A6FF",
    reason_bg="#0D1F3C",
    reason_text_color="#79C0FF",
    show_score=True,
)

ReducePositionSlide = SlideTemplate(
    slide_type=SlideType.REDUCE_POSITION,
    title_prefix="▼ 减仓提示",
    title_color="#F85149",
    header_bg="#2D0F14",
    card_border_color="#F85149",
    badge_color="#F85149",
    reason_bg="#2D0F14",
    reason_text_color="#FFA198",
    show_score=False,
)

ClearPositionSlide = SlideTemplate(
    slide_type=SlideType.CLEAR_POSITION,
    title_prefix="⚠ 清仓提示",
    title_color="#D29922",
    header_bg="#2D1F0A",
    card_border_color="#D29922",
    badge_color="#D29922",
    reason_bg="#2D1F0A",
    reason_text_color="#E3B341",
    show_score=False,
)

RiskWarningSlide = SlideTemplate(
    slide_type=SlideType.RISK_WARNING,
    title_prefix="🛡 风险提示",
    title_color="#D29922",
    header_bg="#1C1A10",
    card_border_color="#D29922",
    badge_color="#D29922",
    reason_bg="#1C1A10",
    reason_text_color="#E3B341",
    show_score=False,
)
