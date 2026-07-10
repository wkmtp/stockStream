"""Full-screen financial data dashboard renderer using matplotlib.

Renders a 1920×1080 dark-theme dashboard with 9 panels:

    ┌──────────────────────────────────────────────────────────┐
    │  📊 财经数据大屏                         更新: 13:09:25  │  ← header
    ├────────────┬────────────┬────────────┬───────────────────┤
    │  上证指数   │  深证成指   │  创业板指   │    北向资金        │  ← row 1: indices
    │  3350.25    │  10880.12  │  2156.88   │ 净流入: +12.50亿   │
    │  +0.85% ↑   │  -0.32% ↓  │  +1.52% ↑  │ 余额:  520.30亿   │
    ├────────────┴────────────┴────────────┴───────────────────┤
    │  涨跌统计                                  资金流向       │  ← row 2: stats
    │  🟢 上涨 2856  🔴 下跌 1203  ⚪ 平盘 341  主力 +5.2亿     │
    │  📈 涨停 68   📉 跌停 12                   超大 +8.1亿     │
    │  上涨占比: 64.8%                            大单 -2.9亿    │
    ├──────────────────────────────────────────────────────────┤
    │              🔥 热点板块 TOP10                            │  ← row 3: sectors
    │  1. 半导体 +3.52%  领涨: 北方华创 +8.2%                  │
    │  2. AI芯片 +2.85%  领涨: 寒武纪 +6.5%                    │
    │  ...                                                     │
    ├──────────────────────────────────────────────────────────┤
    │  ⚠ 数据来源: 东方财富 · AkShare  |  AI生成 仅供参考       │  ← footer
    └──────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import io
import logging
import math
from datetime import datetime, timezone
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── matplotlib setup ──────────────────────────────────────────────────────
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties

# ── Chinese font discovery ────────────────────────────────────────────────
_CHINESE_FONT_CANDIDATES = [
    "SimHei", "Microsoft YaHei", "PingFang SC", "Heiti SC",
    "Noto Sans CJK SC", "WenQuanYi Micro Hei", "sans-serif",
]

def _find_chinese_font() -> str:
    from matplotlib.font_manager import fontManager
    available = {f.name for f in fontManager.ttflist}
    for name in _CHINESE_FONT_CANDIDATES:
        if name in available:
            return name
    return "sans-serif"


_FONT_FAMILY = _find_chinese_font()

def _make_font(size: int = 12) -> FontProperties:
    return FontProperties(family=_FONT_FAMILY, size=size)


# ── colour palette (matching chart_engine) ────────────────────────────────

class DC:
    """Dashboard Colors — dark theme matching the project palette."""
    BG = "#0D1117"
    PANEL_BG = "#161B22"
    GRID = "#21262D"
    TEXT = "#C9D1D9"
    TEXT_DIM = "#8B949E"
    WHITE = "#F0F6FC"
    GREEN = "#3FB950"
    RED = "#F85149"
    BLUE = "#58A6FF"
    ORANGE = "#D29922"
    PURPLE = "#BC8CFF"
    YELLOW = "#E3B341"
    CYAN = "#39D2C0"
    PINK = "#F778BA"

    @staticmethod
    def change_color(val: float) -> str:
        if val > 0:
            return DC.RED   # A-share: red = up
        if val < 0:
            return DC.GREEN
        return DC.TEXT_DIM


# ── imports from sibling modules ──────────────────────────────────────────
from stockstream.dashboard_renderer.models import (
    AdvanceDeclineStats,
    DashboardConfig,
    DashboardData,
    DashboardResult,
    FundFlowSummary,
    HotSector,
    IndexData,
    LimitStats,
    NorthboundFlow,
)


# ══════════════════════════════════════════════════════════════════════════
# Public rendering API
# ══════════════════════════════════════════════════════════════════════════

def render_dashboard(
    data: DashboardData,
    cfg: DashboardConfig | None = None,
) -> DashboardResult:
    """Render a full-screen financial data dashboard.

    Args:
        data: Collected dashboard data snapshot.
        cfg: Rendering config (dimensions, DPI, etc.)

    Returns:
        DashboardResult with RGBA numpy array and PNG bytes.
    """
    import time as _time
    t_start = _time.perf_counter()

    if cfg is None:
        cfg = DashboardConfig()

    w_px, h_px = cfg.width, cfg.height
    dpi = cfg.dpi
    w_in, h_in = w_px / dpi, h_px / dpi

    fig = plt.figure(figsize=(w_in, h_in), dpi=dpi, facecolor=DC.BG)
    fig.subplots_adjust(left=0, right=1, bottom=0, top=1, wspace=0, hspace=0)

    # ── Layout grid (relative coords 0-1) ────────────────────────
    # header:      y=[0.94, 1.0]
    # row1 index:  y=[0.74, 0.93]
    # row2 stats:  y=[0.54, 0.73]
    # row3 sector: y=[0.20, 0.53]
    # footer:      y=[0.08, 0.19]
    # bottom bar:  y=[0.0,  0.07]

    _render_header(fig, data, cfg)
    _render_index_row(fig, data, cfg)
    _render_stats_row(fig, data, cfg)
    _render_sector_row(fig, data, cfg)
    _render_footer(fig, data, cfg)

    # ── Render to RGBA buffer ────────────────────────────────────
    buf = io.BytesIO()
    fig.savefig(buf, format="rgba", dpi=dpi, facecolor=DC.BG,
                edgecolor="none", pad_inches=0)
    plt.close(fig)
    buf.seek(0)

    rgba = np.frombuffer(buf.getvalue(), dtype=np.uint8).reshape(h_px, w_px, 4)

    # ── Encode PNG ───────────────────────────────────────────────
    from PIL import Image as PILImage
    png_buf = io.BytesIO()
    img = PILImage.fromarray(rgba, mode="RGBA")
    img.save(png_buf, format="PNG", optimize=True)
    png_bytes = png_buf.getvalue()

    render_ms = (_time.perf_counter() - t_start) * 1000.0
    return DashboardResult(
        rgba=rgba,
        png_bytes=png_bytes,
        render_time_ms=render_ms,
        width=w_px,
        height=h_px,
        data=data,
    )


# ══════════════════════════════════════════════════════════════════════════
# Panel renderers
# ══════════════════════════════════════════════════════════════════════════

def _render_header(fig: plt.Figure, data: DashboardData, cfg: DashboardConfig) -> None:
    """Top header bar: title + timestamp."""
    # Full-width header box
    header_ax = fig.add_axes([0.0, 0.94, 1.0, 0.06], facecolor=DC.BG)

    # Title
    header_ax.text(0.02, 0.5, "📊 财经数据大屏", transform=header_ax.transAxes,
                   fontsize=24, fontproperties=_make_font(24), color=DC.WHITE,
                   va="center", weight="bold")

    # Timestamp
    ts_str = data.fetched_at.strftime("%Y-%m-%d %H:%M:%S")
    header_ax.text(0.98, 0.5, f"更新: {ts_str}", transform=header_ax.transAxes,
                   fontsize=12, fontproperties=_make_font(12), color=DC.TEXT_DIM,
                   va="center", ha="right")

    header_ax.set_xlim(0, 1)
    header_ax.set_ylim(0, 1)
    header_ax.axis("off")

    # Separator line
    sep_ax = fig.add_axes([0.0, 0.935, 1.0, 0.001], facecolor=DC.BG)
    sep_ax.axhline(y=0.5, color=DC.GRID, linewidth=1.0)
    sep_ax.axis("off")


def _render_index_row(fig: plt.Figure, data: DashboardData, cfg: DashboardConfig) -> None:
    """Row 1: 3 index cards + 1 northbound card."""
    indices = data.indices
    nb = data.northbound

    # Define 4 columns
    col_positions = [0.01, 0.255, 0.50, 0.745]
    col_width = 0.23

    index_names = ["上证指数", "深证成指", "创业板指"]

    for i, name in enumerate(index_names):
        x = col_positions[i]
        _draw_index_card(fig, x, 0.75, col_width, 0.18,
                         indices.get(name), name)

    # Northbound card (column 4)
    _draw_northbound_card(fig, col_positions[3], 0.75, col_width, 0.18, nb)


def _draw_index_card(
    fig: plt.Figure, x: float, y: float,
    w: float, h: float, idx: IndexData | None, name: str,
) -> None:
    """Draw a single index quote card with coloured border accent."""
    ax = fig.add_axes([x, y, w, h], facecolor=DC.PANEL_BG)

    # Accent border (coloured strip at top)
    border_ax = fig.add_axes([x, y + h - 0.005, w, 0.008], facecolor=DC.BG)
    accent_color = DC.BLUE
    if idx:
        accent_color = DC.change_color(idx.change_pct)
    border_ax.axhline(y=0.5, color=accent_color, linewidth=3.0)
    border_ax.axis("off")

    # Panel border
    for spine in ax.spines.values():
        spine.set_color(DC.GRID)
        spine.set_linewidth(0.8)

    if idx is None or idx.close == 0:
        ax.text(0.5, 0.5, f"{name}\n等待数据...", transform=ax.transAxes,
                ha="center", va="center", fontsize=14, fontproperties=_make_font(14),
                color=DC.TEXT_DIM)
        ax.set_xlim(0, 1); ax.set_ylim(0, 1)
        ax.set_xticks([]); ax.set_yticks([])
        return

    # Index name
    ax.text(0.08, 0.85, name, transform=ax.transAxes,
            fontsize=13, fontproperties=_make_font(13), color=DC.TEXT_DIM,
            va="center")

    # Price (big)
    price_str = _fmt_price(idx.close)
    ax.text(0.08, 0.52, price_str, transform=ax.transAxes,
            fontsize=26, fontproperties=_make_font(26), color=DC.WHITE,
            va="center", weight="bold")

    # Change / change%
    change_str = f"{idx.change:+.2f}  {idx.change_pct:+.2f}%"
    change_color = DC.change_color(idx.change_pct)
    arrow = "▲" if idx.change_pct > 0 else ("▼" if idx.change_pct < 0 else "—")
    ax.text(0.08, 0.20, f"{arrow} {change_str}", transform=ax.transAxes,
            fontsize=14, fontproperties=_make_font(14), color=change_color,
            va="center", weight="bold")

    # Amount
    amount_yi = idx.amount / 1e8 if idx.amount else 0
    ax.text(0.08, 0.02, f"成交 {amount_yi:.1f}亿", transform=ax.transAxes,
            fontsize=10, fontproperties=_make_font(10), color=DC.TEXT_DIM,
            va="bottom")

    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.set_xticks([]); ax.set_yticks([])


def _draw_northbound_card(
    fig: plt.Figure, x: float, y: float,
    w: float, h: float, nb: NorthboundFlow,
) -> None:
    """Draw northbound flow card."""
    ax = fig.add_axes([x, y, w, h], facecolor=DC.PANEL_BG)

    # Accent border
    border_ax = fig.add_axes([x, y + h - 0.005, w, 0.008], facecolor=DC.BG)
    accent_color = DC.RED if nb.net_inflow > 0 else (DC.GREEN if nb.net_inflow < 0 else DC.BLUE)
    border_ax.axhline(y=0.5, color=accent_color, linewidth=3.0)
    border_ax.axis("off")

    for spine in ax.spines.values():
        spine.set_color(DC.GRID)
        spine.set_linewidth(0.8)

    # Title
    ax.text(0.08, 0.85, "北向资金", transform=ax.transAxes,
            fontsize=13, fontproperties=_make_font(13), color=DC.TEXT_DIM, va="center")

    # Net inflow
    inflow_str = f"{nb.net_inflow_yi:+.2f}亿"
    inflow_color = DC.RED if nb.net_inflow > 0 else (DC.GREEN if nb.net_inflow < 0 else DC.TEXT)
    arrow = "▲" if nb.net_inflow > 0 else ("▼" if nb.net_inflow < 0 else "—")
    ax.text(0.08, 0.50, f"{arrow} 净流入 {inflow_str}", transform=ax.transAxes,
            fontsize=18, fontproperties=_make_font(18), color=inflow_color,
            va="center", weight="bold")

    # Balance
    balance_yi = nb.balance / 1e8 if nb.balance else 0
    ax.text(0.08, 0.20, f"资金余额  {balance_yi:.1f}亿", transform=ax.transAxes,
            fontsize=12, fontproperties=_make_font(12), color=DC.TEXT, va="center")

    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.set_xticks([]); ax.set_yticks([])


def _render_stats_row(fig: plt.Figure, data: DashboardData, cfg: DashboardConfig) -> None:
    """Row 2: advance/decline stats (left 50%) + fund flow (right 50%)."""
    ad = data.advance_decline
    ls = data.limit_stats
    ff = data.fund_flow

    # ── Left: advance/decline panel ─────────────────────────────
    ad_ax = fig.add_axes([0.01, 0.55, 0.48, 0.18], facecolor=DC.PANEL_BG)

    # Accent border
    border_ax = fig.add_axes([0.01, 0.55 + 0.18 - 0.005, 0.48, 0.008], facecolor=DC.BG)
    border_ax.axhline(y=0.5, color=DC.BLUE, linewidth=3.0)
    border_ax.axis("off")

    for spine in ad_ax.spines.values():
        spine.set_color(DC.GRID); spine.set_linewidth(0.8)

    # Title
    ad_ax.text(0.03, 0.88, "涨跌统计", transform=ad_ax.transAxes,
               fontsize=14, fontproperties=_make_font(14), color=DC.TEXT_DIM, va="center")

    # Build stats bar as text
    if ad.total > 0:
        # Progress bar style text
        line_y = 0.62
        ad_ax.text(0.03, line_y,
                   f"🟢 上涨 {ad.up_count}    🔴 下跌 {ad.down_count}    ⚪ 平盘 {ad.flat_count}",
                   transform=ad_ax.transAxes,
                   fontsize=16, fontproperties=_make_font(16), color=DC.TEXT, va="center")

        # Limit up/down
        line_y2 = 0.35
        ad_ax.text(0.03, line_y2,
                   f"📈 涨停 {ls.limit_up} 家    📉 跌停 {ls.limit_down} 家",
                   transform=ad_ax.transAxes,
                   fontsize=14, fontproperties=_make_font(14), color=DC.TEXT, va="center")

        # Ratio
        line_y3 = 0.10
        ad_ax.text(0.03, line_y3,
                   f"上涨占比: {ad.up_ratio:.1f}%  |  总股票数: {ad.total}",
                   transform=ad_ax.transAxes,
                   fontsize=11, fontproperties=_make_font(11), color=DC.TEXT_DIM, va="center")

        # Draw a horizontal progress bar (up ratio)
        bar_ax = fig.add_axes([0.03, 0.555, 0.44, 0.012], facecolor=DC.BG)
        bar_ax.barh(0.5, ad.up_ratio / 100, height=0.8, color=DC.RED, alpha=0.7)
        bar_ax.barh(0.5, 1.0, height=0.8, color=DC.GRID, alpha=0.3,
                    left=ad.up_ratio / 100)
        bar_ax.set_xlim(0, 1); bar_ax.set_ylim(0, 1)
        bar_ax.axis("off")
    else:
        ad_ax.text(0.5, 0.5, "等待涨跌数据...", transform=ad_ax.transAxes,
                   ha="center", va="center", fontsize=16,
                   fontproperties=_make_font(16), color=DC.TEXT_DIM)

    ad_ax.set_xlim(0, 1); ad_ax.set_ylim(0, 1)
    ad_ax.set_xticks([]); ad_ax.set_yticks([])

    # ── Right: fund flow panel ──────────────────────────────────
    ff_ax = fig.add_axes([0.51, 0.55, 0.48, 0.18], facecolor=DC.PANEL_BG)

    border_ax2 = fig.add_axes([0.51, 0.55 + 0.18 - 0.005, 0.48, 0.008], facecolor=DC.BG)
    border_ax2.axhline(y=0.5, color=DC.ORANGE, linewidth=3.0)
    border_ax2.axis("off")

    for spine in ff_ax.spines.values():
        spine.set_color(DC.GRID); spine.set_linewidth(0.8)

    ff_ax.text(0.03, 0.88, "全市场资金流向", transform=ff_ax.transAxes,
               fontsize=14, fontproperties=_make_font(14), color=DC.TEXT_DIM, va="center")

    if ff.main_net_inflow != 0 or ff.super_large_net != 0:
        items = [
            ("主力净流入", ff.main_net_yi, 0.62),
            ("超大单", round(ff.super_large_net / 1e8, 2), 0.42),
            ("大单", round(ff.large_net / 1e8, 2), 0.22),
        ]
        for label, val, yy in items:
            color = DC.RED if val > 0 else (DC.GREEN if val < 0 else DC.TEXT_DIM)
            sign = "+" if val > 0 else ""
            ff_ax.text(0.08, yy, f"{label}: {sign}{val:.2f}亿", transform=ff_ax.transAxes,
                       fontsize=14, fontproperties=_make_font(14), color=color,
                       va="center", weight="bold")
    else:
        ff_ax.text(0.5, 0.5, "等待资金流向数据...", transform=ff_ax.transAxes,
                   ha="center", va="center", fontsize=16,
                   fontproperties=_make_font(16), color=DC.TEXT_DIM)

    ff_ax.set_xlim(0, 1); ff_ax.set_ylim(0, 1)
    ff_ax.set_xticks([]); ff_ax.set_yticks([])


def _render_sector_row(fig: plt.Figure, data: DashboardData, cfg: DashboardConfig) -> None:
    """Row 3: hot sectors TOP10."""
    sectors = data.hot_sectors

    ax = fig.add_axes([0.01, 0.21, 0.98, 0.32], facecolor=DC.PANEL_BG)

    # Accent border
    border_ax = fig.add_axes([0.01, 0.21 + 0.32 - 0.005, 0.98, 0.008], facecolor=DC.BG)
    border_ax.axhline(y=0.5, color=DC.PURPLE, linewidth=3.0)
    border_ax.axis("off")

    for spine in ax.spines.values():
        spine.set_color(DC.GRID); spine.set_linewidth(0.8)

    # Title
    ax.text(0.02, 0.94, "🔥 热点板块 TOP10", transform=ax.transAxes,
            fontsize=15, fontproperties=_make_font(15), color=DC.TEXT_DIM, va="center")

    if not sectors:
        ax.text(0.5, 0.5, "等待板块数据...", transform=ax.transAxes,
                ha="center", va="center", fontsize=18,
                fontproperties=_make_font(18), color=DC.TEXT_DIM)
        ax.set_xlim(0, 1); ax.set_ylim(0, 1)
        ax.set_xticks([]); ax.set_yticks([])
        return

    # Draw 2-column sector list
    max_sectors = min(len(sectors), 10)
    col1_count = math.ceil(max_sectors / 2)

    for i, sector in enumerate(sectors[:max_sectors]):
        if i < col1_count:
            col_x = 0.03
            row_idx = i
        else:
            col_x = 0.51
            row_idx = i - col1_count

        y_pos = 0.80 - row_idx * 0.14

        # Rank badge
        rank_color = DC.RED if i < 3 else DC.TEXT_DIM
        ax.text(col_x, y_pos, f"#{i + 1}", transform=ax.transAxes,
                fontsize=12, fontproperties=_make_font(12), color=rank_color,
                va="center", weight="bold")

        # Sector name
        ax.text(col_x + 0.04, y_pos, sector.name, transform=ax.transAxes,
                fontsize=14, fontproperties=_make_font(14), color=DC.WHITE,
                va="center", weight="bold")

        # Change%
        change_color = DC.RED if sector.change_pct > 0 else DC.GREEN
        arrow = "▲" if sector.change_pct > 0 else "▼"
        ax.text(col_x + 0.18, y_pos, f"{arrow} {sector.change_pct:+.2f}%",
                transform=ax.transAxes, fontsize=14,
                fontproperties=_make_font(14), color=change_color,
                va="center", weight="bold")

        # Leading stock
        if sector.leading_stock:
            ls_change = sector.leading_change
            ls_color = DC.RED if ls_change > 0 else DC.GREEN
            ax.text(col_x + 0.32, y_pos,
                    f"领涨: {sector.leading_stock}  {ls_change:+.2f}%",
                    transform=ax.transAxes, fontsize=11,
                    fontproperties=_make_font(11), color=ls_color, va="center")

    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.set_xticks([]); ax.set_yticks([])


def _render_footer(fig: plt.Figure, data: DashboardData, cfg: DashboardConfig) -> None:
    """Bottom disclaimer bar."""
    footer_ax = fig.add_axes([0.0, 0.08, 1.0, 0.12], facecolor=DC.BG)

    # Separator line at top of footer
    footer_ax.axhline(y=0.95, color=DC.GRID, linewidth=0.8)

    footer_ax.text(0.5, 0.55, "数据来源: 东方财富 · AkShare  |  AI生成 仅供参考  |  投资有风险 入市需谨慎",
                   transform=footer_ax.transAxes,
                   fontsize=11, fontproperties=_make_font(11), color=DC.TEXT_DIM,
                   va="center", ha="center")

    footer_ax.set_xlim(0, 1); footer_ax.set_ylim(0, 1)
    footer_ax.axis("off")


# ── helpers ──────────────────────────────────────────────────────────────

def _fmt_price(price: float) -> str:
    """Format a price with appropriate precision."""
    if price >= 1000:
        return f"{price:,.2f}"
    return f"{price:.2f}"
