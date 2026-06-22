"""Sector heatmap & cloud-map renderers using matplotlib.

Renders 5 chart types:
    1. Heatmap tile  — squarified treemap, colour-coded by change%
    2. Sector cloud  — wordcloud-style bubble chart
    3. Top20 gainers — horizontal bar chart
    4. Top20 fund flow — horizontal bar chart
    5. Top20 volume   — horizontal bar chart
    6. Composite dashboard — 4-in-1 overview

All renderers return numpy RGBA uint8 arrays and use the project's
dark theme colour palette (consistent with chart_engine).
"""

from __future__ import annotations

import io
import logging
import math
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


# ── colour palette (matching chart_engine.C) ─────────────────────────────

class C:
    BG = "#0D1117"
    PANEL_BG = "#161B22"
    GRID = "#21262D"
    TEXT = "#C9D1D9"
    TEXT_DIM = "#8B949E"
    GREEN = "#3FB950"
    RED = "#F85149"
    BLUE = "#58A6FF"
    ORANGE = "#D29922"
    PURPLE = "#BC8CFF"
    YELLOW = "#E3B341"
    WHITE = "#F0F6FC"
    CYAN = "#39D2C0"
    PINK = "#F778BA"

    @staticmethod
    def change_color(val: float) -> str:
        """Green for positive, red for negative, dim for zero."""
        if val > 0:
            return C.GREEN
        if val < 0:
            return C.RED
        return C.TEXT_DIM

    @staticmethod
    def heatmap_color(val: float, vmin: float = -5.0, vmax: float = 5.0) -> str:
        """Map a change_pct value to a heatmap colour (green→white→red)."""
        if val > 0:
            t = min(val / max(vmax, 0.01), 1.0)
            r = int(13 + (63 - 13) * (1 - t))
            g = int(17 + (185 - 17) * t)
            b = int(23 + (80 - 23) * (1 - t))
            return f"#{r:02X}{g:02X}{b:02X}"
        elif val < 0:
            t = min(abs(val) / max(abs(vmin), 0.01), 1.0)
            r = int(13 + (248 - 13) * t)
            g = int(17 + (81 - 17) * (1 - t))
            b = int(23 + (73 - 23) * (1 - t))
            return f"#{r:02X}{g:02X}{b:02X}"
        return C.TEXT_DIM


# ── imports from sibling modules ──────────────────────────────────────────

from stockstream.heatmap_engine.models import HeatmapType, SectorData, SectorSnapshot


# ══════════════════════════════════════════════════════════════════════════
# Public rendering API
# ══════════════════════════════════════════════════════════════════════════

def render_heatmap(
    snapshot: SectorSnapshot,
    chart_type: HeatmapType,
    width_px: int = 1440,
    height_px: int = 880,
    dpi: int = 100,
) -> np.ndarray | None:
    """Render a heatmap/chart from a sector snapshot.

    Args:
        snapshot: SectorSnapshot with all sector data.
        chart_type: Which chart to render.
        width_px, height_px: Output dimensions in pixels.
        dpi: DPI for rendering.

    Returns:
        numpy uint8 RGBA array (height_px, width_px, 4), or None if no data.
    """
    if not snapshot.sectors:
        return _render_empty_placeholder(chart_type.label, width_px, height_px, dpi)

    renderer_map = {
        HeatmapType.HEATMAP_TILE: _render_heatmap_tile,
        HeatmapType.SECTOR_CLOUD: _render_sector_cloud,
        HeatmapType.TOP20_GAINERS: _render_top20_gainers,
        HeatmapType.TOP20_FUND_FLOW: _render_top20_fund_flow,
        HeatmapType.TOP20_VOLUME: _render_top20_volume,
        HeatmapType.COMPOSITE_DASHBOARD: _render_composite_dashboard,
    }
    fn = renderer_map.get(chart_type)
    if fn is None:
        raise ValueError(f"Unknown heatmap chart type: {chart_type}")
    return fn(snapshot, width_px, height_px, dpi)


def render_all(
    snapshot: SectorSnapshot,
    width_px: int = 1440,
    height_px: int = 880,
    dpi: int = 100,
) -> dict[HeatmapType, np.ndarray | None]:
    """Render all heatmap chart types for a snapshot.

    Returns a dict mapping HeatmapType → RGBA array.
    """
    results: dict[HeatmapType, np.ndarray | None] = {}
    for ct in HeatmapType:
        if ct == HeatmapType.COMPOSITE_DASHBOARD:
            continue  # dashboard is heavy, skip by default
        try:
            results[ct] = render_heatmap(snapshot, ct, width_px, height_px, dpi)
        except Exception as exc:
            logger.exception("Render failed for %s: %s", ct.value, exc)
            results[ct] = None
    return results


# ══════════════════════════════════════════════════════════════════════════
# Renderer 1: Treemap-style sector heatmap
# ══════════════════════════════════════════════════════════════════════════

def _render_heatmap_tile(
    snapshot: SectorSnapshot,
    w: int, h: int, dpi: int,
) -> np.ndarray:
    """Squarified treemap: each sector is a coloured tile, size ~ abs(change%)."""
    font = _make_font()
    w_in, h_in = w / dpi, h / dpi
    sectors = snapshot.sectors[:60]  # top 60 for visual clarity

    # Compute tile layout using simple grid packing
    cols = 8
    rows = math.ceil(len(sectors) / cols)
    cell_w = 1.0 / cols
    cell_h = 1.0 / rows

    fig = plt.figure(figsize=(w_in, h_in), dpi=dpi, facecolor=C.BG)
    ax = fig.add_subplot(111, facecolor=C.BG)

    # Compute vmin/vmax from data
    changes = [s.change_pct for s in sectors]
    vmin, vmax = min(changes) if changes else -5, max(changes) if changes else 5
    vrange = max(abs(vmin), abs(vmax), 0.5)

    for i, sector in enumerate(sectors):
        row = i // cols
        col = i % cols
        x = col * cell_w + cell_w * 0.02
        y = 1.0 - (row + 1) * cell_h + cell_h * 0.02
        rw = cell_w * 0.96
        rh = cell_h * 0.92

        color = C.heatmap_color(sector.change_pct, -vrange, vrange)
        rect = plt.Rectangle((x, y), rw, rh, facecolor=color, edgecolor=C.GRID,
                             linewidth=0.5, alpha=0.9, transform=ax.transAxes)
        ax.add_patch(rect)

        # Sector name (short)
        name = sector.name[:4]
        font_size = max(6, min(10, 90 / len(sectors) * 3))
        ax.text(x + rw / 2, y + rh * 0.58, name,
                transform=ax.transAxes, ha="center", va="center",
                fontsize=font_size, fontproperties=_make_font(font_size),
                color=C.WHITE, weight="bold")

        # Change %
        ax.text(x + rw / 2, y + rh * 0.25, f"{sector.change_pct:+.2f}%",
                transform=ax.transAxes, ha="center", va="center",
                fontsize=max(5, font_size - 2), fontproperties=_make_font(max(5, font_size - 2)),
                color=C.change_color(sector.change_pct))

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # Title
    fig.suptitle("A股板块热力图", fontproperties=_make_font(18),
                 color=C.WHITE, y=0.98, x=0.02, ha="left")

    # Legend bar
    cbar_ax = fig.add_axes([0.02, 0.01, 0.96, 0.02])
    gradient = np.linspace(-vrange, vrange, 256).reshape(1, -1)
    cbar_ax.imshow(gradient, aspect="auto", cmap="RdYlGn", extent=[-vrange, vrange, 0, 1])
    cbar_ax.set_yticks([])
    cbar_ax.set_xticks([-vrange, 0, vrange])
    cbar_ax.set_xticklabels([f"{vmin:.1f}%", "0%", f"{vmax:.1f}%"],
                            fontsize=8, color=C.TEXT_DIM)
    for spine in cbar_ax.spines.values():
        spine.set_visible(False)

    buf = io.BytesIO()
    fig.savefig(buf, format="rgba", dpi=dpi, facecolor=C.BG, edgecolor="none", pad_inches=0)
    plt.close(fig)
    buf.seek(0)
    return np.frombuffer(buf.getvalue(), dtype=np.uint8).reshape(h, w, 4)


# ══════════════════════════════════════════════════════════════════════════
# Renderer 2: Wordcloud-style sector cloud (bubble chart)
# ══════════════════════════════════════════════════════════════════════════

def _render_sector_cloud(
    snapshot: SectorSnapshot,
    w: int, h: int, dpi: int,
) -> np.ndarray:
    """Bubble chart: each sector is a circle, size ~ abs(change%), colour ~ direction."""
    font = _make_font()
    w_in, h_in = w / dpi, h / dpi

    sectors = sorted(snapshot.sectors, key=lambda s: abs(s.change_pct), reverse=True)[:50]

    fig = plt.figure(figsize=(w_in, h_in), dpi=dpi, facecolor=C.BG)
    ax = fig.add_subplot(111, facecolor=C.BG)

    # Place bubbles in a spiral layout
    max_abs_change = max(abs(s.change_pct) for s in sectors) if sectors else 5.0
    cx, cy = 0.5, 0.5
    angle = 0.0
    radius = 0.0

    for sector in sectors:
        size = max(20, abs(sector.change_pct) / max(max_abs_change, 0.01) * 600)
        color = C.change_color(sector.change_pct)
        alpha = 0.35 + abs(sector.change_pct) / max(max_abs_change, 0.01) * 0.5

        # Spiral placement
        x = cx + math.cos(angle) * radius
        y = cy + math.sin(angle) * radius
        angle += 0.5
        radius += 0.042

        ax.scatter(x, y, s=size, c=color, alpha=alpha, edgecolors=C.GRID,
                   linewidth=0.3, zorder=2)

        # Label only for top sectors
        if abs(sector.change_pct) >= max_abs_change * 0.3:
            ax.text(x, y, sector.name[:4], ha="center", va="center",
                    fontsize=8, fontproperties=_make_font(8), color=C.WHITE,
                    weight="bold", zorder=3)

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_aspect("equal")
    ax.axis("off")

    fig.suptitle("A股板块云图", fontproperties=_make_font(18),
                 color=C.WHITE, y=0.98, x=0.02, ha="left")

    # Legend
    legend_ax = fig.add_axes([0.02, 0.02, 0.2, 0.06])
    legend_ax.scatter([0.15], [0.5], s=60, c=C.GREEN, alpha=0.6)
    legend_ax.text(0.35, 0.5, "上涨板块", transform=legend_ax.transAxes,
                   fontsize=7, color=C.GREEN, va="center", fontproperties=_make_font(7))
    legend_ax.scatter([0.65], [0.5], s=60, c=C.RED, alpha=0.6)
    legend_ax.text(0.85, 0.5, "下跌板块", transform=legend_ax.transAxes,
                   fontsize=7, color=C.RED, va="center", fontproperties=_make_font(7))
    legend_ax.set_xlim(0, 1); legend_ax.set_ylim(0, 1)
    legend_ax.axis("off")

    buf = io.BytesIO()
    fig.savefig(buf, format="rgba", dpi=dpi, facecolor=C.BG, edgecolor="none", pad_inches=0)
    plt.close(fig)
    buf.seek(0)
    return np.frombuffer(buf.getvalue(), dtype=np.uint8).reshape(h, w, 4)


# ══════════════════════════════════════════════════════════════════════════
# Renderer 3: Top20 gainers — horizontal bar chart
# ══════════════════════════════════════════════════════════════════════════

def _render_top20_gainers(
    snapshot: SectorSnapshot,
    w: int, h: int, dpi: int,
) -> np.ndarray:
    """Top 20 sectors by change% — horizontal bar chart."""
    return _render_topn_bar(
        snapshot.top_gainers,
        value_key="change_pct",
        title="板块涨幅排行 TOP20",
        value_label="涨跌幅 (%)",
        w=w, h=h, dpi=dpi,
        sort_desc=True,
    )


# ══════════════════════════════════════════════════════════════════════════
# Renderer 4: Top20 fund flow — horizontal bar chart
# ══════════════════════════════════════════════════════════════════════════

def _render_top20_fund_flow(
    snapshot: SectorSnapshot,
    w: int, h: int, dpi: int,
) -> np.ndarray:
    """Top 20 sectors by main fund net inflow — horizontal bar chart."""
    return _render_topn_bar(
        snapshot.top_fund_flow,
        value_key="fund_flow",
        title="板块资金流入 TOP20",
        value_label="主力净流入 (亿元)",
        w=w, h=h, dpi=dpi,
        sort_desc=True,
        value_formatter=lambda v: f"{v/1e8:+.2f}亿",
    )


# ══════════════════════════════════════════════════════════════════════════
# Renderer 5: Top20 volume — horizontal bar chart
# ══════════════════════════════════════════════════════════════════════════

def _render_top20_volume(
    snapshot: SectorSnapshot,
    w: int, h: int, dpi: int,
) -> np.ndarray:
    """Top 20 sectors by turnover volume — horizontal bar chart."""
    return _render_topn_bar(
        snapshot.top_volume,
        value_key="volume",
        title="板块成交额 TOP20",
        value_label="成交额 (亿元)",
        w=w, h=h, dpi=dpi,
        sort_desc=True,
        value_formatter=lambda v: f"{v/1e8:.2f}亿",
    )


# ══════════════════════════════════════════════════════════════════════════
# Renderer 6: Composite dashboard (4-in-1)
# ══════════════════════════════════════════════════════════════════════════

def _render_composite_dashboard(
    snapshot: SectorSnapshot,
    w: int, h: int, dpi: int,
) -> np.ndarray:
    """4-panel dashboard: gainers | fund flow | volume | heatmap tile."""
    font = _make_font()
    w_in, h_in = w / dpi, h / dpi

    fig = plt.figure(figsize=(w_in, h_in), dpi=dpi, facecolor=C.BG)
    gs = fig.add_gridspec(2, 2, hspace=0.35, wspace=0.3,
                          left=0.05, right=0.97, top=0.93, bottom=0.05)

    # Panel 1: Top10 gainers
    ax1 = fig.add_subplot(gs[0, 0], facecolor=C.BG)
    _draw_mini_barh(ax1, snapshot.top_gainers[:10], "change_pct",
                    "涨跌幅 (%)", font, sort_desc=True,
                    value_fmt=lambda v: f"{v:+.2f}%")
    ax1.set_title("涨幅TOP10", fontproperties=_make_font(13), color=C.WHITE, pad=6)

    # Panel 2: Top10 fund flow
    ax2 = fig.add_subplot(gs[0, 1], facecolor=C.BG)
    _draw_mini_barh(ax2, snapshot.top_fund_flow[:10], "fund_flow",
                    "主力净流入 (亿)", font, sort_desc=True,
                    value_fmt=lambda v: f"{v/1e8:+.2f}亿")
    ax2.set_title("资金流入TOP10", fontproperties=_make_font(13), color=C.WHITE, pad=6)

    # Panel 3: Top10 volume
    ax3 = fig.add_subplot(gs[1, 0], facecolor=C.BG)
    _draw_mini_barh(ax3, snapshot.top_volume[:10], "volume",
                    "成交额 (亿)", font, sort_desc=True,
                    value_fmt=lambda v: f"{v/1e8:.2f}亿")
    ax3.set_title("成交额TOP10", fontproperties=_make_font(13), color=C.WHITE, pad=6)

    # Panel 4: mini heatmap tile grid
    ax4 = fig.add_subplot(gs[1, 1], facecolor=C.BG)
    _draw_mini_heatmap_tile(ax4, snapshot.sectors[:36], font)
    ax4.set_title("板块热力图", fontproperties=_make_font(13), color=C.WHITE, pad=6)

    # Global title
    fig.suptitle("A股板块实时统计  ·  综合仪表盘",
                 fontproperties=_make_font(18), color=C.WHITE, y=0.98, x=0.02, ha="left")

    # Timestamp
    ts_str = snapshot.collected_at.strftime("%H:%M:%S")
    fig.text(0.97, 0.99, f"更新: {ts_str}", ha="right", va="top",
             fontsize=9, color=C.TEXT_DIM, fontproperties=_make_font(9))

    buf = io.BytesIO()
    fig.savefig(buf, format="rgba", dpi=dpi, facecolor=C.BG, edgecolor="none", pad_inches=0)
    plt.close(fig)
    buf.seek(0)
    return np.frombuffer(buf.getvalue(), dtype=np.uint8).reshape(h, w, 4)


# ══════════════════════════════════════════════════════════════════════════
# Shared drawing helpers
# ══════════════════════════════════════════════════════════════════════════

def _render_topn_bar(
    sectors: list[SectorData],
    value_key: str,
    title: str,
    value_label: str,
    w: int, h: int, dpi: int,
    sort_desc: bool = True,
    value_formatter=None,
) -> np.ndarray:
    """Generic TOP-N horizontal bar chart renderer."""
    font = _make_font()
    w_in, h_in = w / dpi, h / dpi

    fig = plt.figure(figsize=(w_in, h_in), dpi=dpi, facecolor=C.BG)
    ax = fig.add_subplot(111, facecolor=C.BG)

    if value_formatter is None:
        value_formatter = lambda v: f"{v:+.2f}"

    _draw_mini_barh(ax, sectors, value_key, value_label, font,
                    sort_desc=sort_desc, value_fmt=value_formatter)

    ax.set_title(title, fontproperties=_make_font(18), color=C.WHITE, pad=15, loc="left")

    buf = io.BytesIO()
    fig.savefig(buf, format="rgba", dpi=dpi, facecolor=C.BG, edgecolor="none", pad_inches=0)
    plt.close(fig)
    buf.seek(0)
    return np.frombuffer(buf.getvalue(), dtype=np.uint8).reshape(h, w, 4)


def _draw_mini_barh(
    ax,
    sectors: list[SectorData],
    value_key: str,
    value_label: str,
    font: FontProperties,
    sort_desc: bool = True,
    value_fmt=None,
) -> None:
    """Draw a horizontal bar chart on an existing axes."""
    if not sectors:
        ax.text(0.5, 0.5, "暂无数据", transform=ax.transAxes,
                ha="center", va="center", fontsize=14, fontproperties=font,
                color=C.TEXT_DIM)
        ax.axis("off")
        return

    if value_fmt is None:
        value_fmt = lambda v: f"{v:+.2f}"

    # Sort
    if sort_desc:
        items = sorted(sectors, key=lambda s: getattr(s, value_key, 0), reverse=True)
    else:
        items = sorted(sectors, key=lambda s: getattr(s, value_key, 0))

    names = [s.name[:8] for s in items]
    values = [getattr(s, value_key, 0) for s in items]

    y_pos = range(len(names))
    colors = [C.change_color(v) for v in values]
    bars = ax.barh(y_pos, values, color=colors, height=0.65, alpha=0.85,
                   edgecolor=colors, linewidth=0.3)

    ax.set_yticks(y_pos)
    ax.set_yticklabels(names, fontproperties=font, fontsize=10, color=C.TEXT)
    ax.invert_yaxis()
    ax.set_xlabel(value_label, fontsize=9, color=C.TEXT_DIM, fontproperties=font)

    # Value labels
    for bar, val in zip(bars, values):
        label = value_fmt(val)
        ha = "left" if val >= 0 else "right"
        offset_pct = 0.01
        x_pos = bar.get_width()
        offset = max(abs(x_pos) * offset_pct, 0.05) if x_pos != 0 else 0.05
        if val < 0:
            offset = -offset
        ax.text(x_pos + offset, bar.get_y() + bar.get_height() / 2,
                label, va="center", ha=ha, fontsize=8,
                color=C.TEXT, fontproperties=font)

    ax.axvline(x=0, color=C.TEXT_DIM, linewidth=0.6, alpha=0.4)
    ax.set_facecolor(C.BG)
    ax.tick_params(colors=C.TEXT_DIM, labelsize=9)
    for spine in ax.spines.values():
        spine.set_color(C.GRID)
    ax.grid(True, color=C.GRID, alpha=0.3, linestyle=":", linewidth=0.5, axis="x")


def _draw_mini_heatmap_tile(
    ax,
    sectors: list[SectorData],
    font: FontProperties,
) -> None:
    """Draw a compact treemap grid on existing axes."""
    if not sectors:
        ax.text(0.5, 0.5, "暂无数据", transform=ax.transAxes,
                ha="center", va="center", fontsize=12, fontproperties=font,
                color=C.TEXT_DIM)
        ax.axis("off")
        return

    cols = 6
    rows = math.ceil(len(sectors) / cols)
    cell_w = 1.0 / cols
    cell_h = 1.0 / rows

    changes = [s.change_pct for s in sectors]
    vmin, vmax = min(changes) if changes else -5, max(changes) if changes else 5
    vrange = max(abs(vmin), abs(vmax), 0.5)

    for i, sector in enumerate(sectors):
        row = i // cols
        col = i % cols
        x = col * cell_w + cell_w * 0.03
        y = 1.0 - (row + 1) * cell_h + cell_h * 0.05
        rw = cell_w * 0.94
        rh = cell_h * 0.88

        color = C.heatmap_color(sector.change_pct, -vrange, vrange)
        rect = plt.Rectangle((x, y), rw, rh, facecolor=color,
                             edgecolor=C.GRID, linewidth=0.3, alpha=0.85,
                             transform=ax.transAxes)
        ax.add_patch(rect)

        fs = max(4, min(7, 70 / rows))
        ax.text(x + rw / 2, y + rh * 0.55, sector.name[:3],
                transform=ax.transAxes, ha="center", va="center",
                fontsize=fs, fontproperties=_make_font(fs), color=C.WHITE)

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")


def _render_empty_placeholder(
    chart_label: str,
    w: int, h: int, dpi: int,
) -> np.ndarray:
    """Render a placeholder image when no data is available."""
    font = _make_font()
    w_in, h_in = w / dpi, h / dpi

    fig = plt.figure(figsize=(w_in, h_in), dpi=dpi, facecolor=C.BG)
    ax = fig.add_subplot(111, facecolor=C.BG)
    ax.text(0.5, 0.5, f"等待板块数据...\n({chart_label})",
            transform=ax.transAxes, ha="center", va="center",
            fontsize=20, fontproperties=_make_font(20), color=C.TEXT_DIM)
    ax.axis("off")

    buf = io.BytesIO()
    fig.savefig(buf, format="rgba", dpi=dpi, facecolor=C.BG, edgecolor="none", pad_inches=0)
    plt.close(fig)
    buf.seek(0)
    return np.frombuffer(buf.getvalue(), dtype=np.uint8).reshape(h, w, 4)
