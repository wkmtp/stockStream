"""Standalone indicator chart renderers for scene engine.

Provides dedicated renderers for each indicator type, callable independently
or from the scene manager. All return numpy RGBA arrays.

Indicators:
    - MACD (DIF/DEA/histogram)
    - RSI (14-period with overbought/oversold zones)
    - Volume standalone
    - Dragon-Tiger Board table
    - Sector Heatmap bar chart
    - Advance/Decline pie + bar chart
    - AI Summary text card
"""

from __future__ import annotations

import io
import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Force Agg backend
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties

from stockstream.video.chart_renderer import ChartColors, StockChartRenderer
from stockstream.video.subtitle_renderer import FONT_PATH

# ── Chinese font for indicator charts ─────────────────────────────────────

def _make_font(size: int = 12) -> FontProperties:
    fp = FontProperties()
    if FONT_PATH:
        try:
            from matplotlib.font_manager import fontManager
            fp = FontProperties(fname=FONT_PATH, size=size)
        except Exception:
            pass
    return fp


# ── MACD renderer ─────────────────────────────────────────────────────────

def render_macd(
    symbol: str,
    name: str,
    dif: list[float],
    dea: list[float],
    histogram: list[float],
    kline_data: list[dict],
    width_px: int = 1440,
    height_px: int = 880,
    dpi: int = 100,
) -> np.ndarray:
    """Render MACD indicator: price + DIF/DEA/histogram sub-plot.

    Returns RGBA uint8 numpy array (height_px, width_px, 4).
    """
    w_in = width_px / dpi
    h_in = height_px / dpi
    font = _make_font()

    fig = plt.figure(figsize=(w_in, h_in), dpi=dpi, facecolor=ChartColors.BG)
    gs = fig.add_gridspec(3, 1, height_ratios=[2, 1, 1], hspace=0.05,
                          left=0.06, right=0.98, top=0.94, bottom=0.06)

    # Price sub-plot (top)
    ax_price = fig.add_subplot(gs[0], facecolor=ChartColors.BG)
    _draw_price_overview(ax_price, kline_data, font)

    # MACD sub-plot (middle)
    ax_macd = fig.add_subplot(gs[1], facecolor=ChartColors.BG, sharex=ax_price)
    _draw_macd_subplot(ax_macd, dif, dea, histogram)

    # MACD title bar (bottom, compact)
    ax_info = fig.add_subplot(gs[2], facecolor=ChartColors.PANEL_BG)
    ax_info.set_xticks([])
    ax_info.set_yticks([])
    for spine in ax_info.spines.values():
        spine.set_visible(False)
    color = ChartColors.GREEN if (histogram[-1] if histogram else 0) >= 0 else ChartColors.RED
    latest_dif = dif[-1] if dif else 0
    latest_dea = dea[-1] if dea else 0
    latest_hist = histogram[-1] if histogram else 0
    ax_info.text(0.02, 0.5, f"  {name} ({symbol})  MACD  |  "
                 f"DIF: {latest_dif:.3f}  DEA: {latest_dea:.3f}  "
                 f"柱: {latest_hist:+.3f}",
                 transform=ax_info.transAxes, fontsize=13, fontproperties=font,
                 color=ChartColors.WHITE, va="center",
                 bbox=dict(facecolor=color, alpha=0.2, edgecolor=color,
                           linewidth=1, boxstyle="round,pad=0.4"))

    plt.setp(ax_price.get_xticklabels(), visible=False)
    plt.setp(ax_macd.get_xticklabels(), visible=False)

    buf = io.BytesIO()
    fig.savefig(buf, format="rgba", dpi=dpi, facecolor=ChartColors.BG,
                edgecolor="none", pad_inches=0)
    plt.close(fig)

    buf.seek(0)
    rgba = np.frombuffer(buf.getvalue(), dtype=np.uint8)
    rgba = rgba.reshape(height_px, width_px, 4)
    return rgba


# ── RSI renderer ──────────────────────────────────────────────────────────

def render_rsi(
    symbol: str,
    name: str,
    rsi_values: list[float],
    kline_data: list[dict],
    width_px: int = 1440,
    height_px: int = 880,
    dpi: int = 100,
) -> np.ndarray:
    """Render RSI indicator with overbought/oversold zones.

    Returns RGBA uint8 numpy array.
    """
    w_in = width_px / dpi
    h_in = height_px / dpi
    font = _make_font()

    fig = plt.figure(figsize=(w_in, h_in), dpi=dpi, facecolor=ChartColors.BG)
    gs = fig.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.05,
                          left=0.06, right=0.98, top=0.94, bottom=0.06)

    # Price overview
    ax_price = fig.add_subplot(gs[0], facecolor=ChartColors.BG)
    _draw_price_overview(ax_price, kline_data, font)

    # RSI sub-plot
    ax_rsi = fig.add_subplot(gs[1], facecolor=ChartColors.BG, sharex=ax_price)
    if rsi_values and len(rsi_values) >= 5:
        xs = list(range(len(rsi_values)))
        ax_rsi.plot(xs, rsi_values, color=ChartColors.PURPLE, linewidth=1.8, label="RSI(14)")
        ax_rsi.fill_between(xs, rsi_values, 50,
                            where=np.array(rsi_values) >= 50,
                            color=ChartColors.GREEN + "22", alpha=0.3)
        ax_rsi.fill_between(xs, rsi_values, 50,
                            where=np.array(rsi_values) < 50,
                            color=ChartColors.RED + "22", alpha=0.3)

    # Reference lines
    ax_rsi.axhline(y=70, color=ChartColors.RED, linewidth=1.0, linestyle="--", alpha=0.7)
    ax_rsi.axhline(y=30, color=ChartColors.GREEN, linewidth=1.0, linestyle="--", alpha=0.7)
    ax_rsi.axhline(y=50, color=ChartColors.TEXT_DIM, linewidth=0.5, linestyle=":", alpha=0.4)
    ax_rsi.set_ylim(0, 100)

    # Zone shading
    ax_rsi.axhspan(70, 100, alpha=0.06, color=ChartColors.RED)
    ax_rsi.axhspan(0, 30, alpha=0.06, color=ChartColors.GREEN)

    # Annotations
    ax_rsi.text(0.99, 0.92, "超买区 70", transform=ax_rsi.transAxes,
                ha="right", fontsize=9, color=ChartColors.RED, fontproperties=font)
    ax_rsi.text(0.99, 0.08, "超卖区 30", transform=ax_rsi.transAxes,
                ha="right", fontsize=9, color=ChartColors.GREEN, fontproperties=font)

    ax_rsi.set_facecolor(ChartColors.BG)
    ax_rsi.tick_params(colors=ChartColors.TEXT_DIM, labelsize=9)
    for spine in ax_rsi.spines.values():
        spine.set_color(ChartColors.GRID)
    ax_rsi.grid(True, color=ChartColors.GRID, alpha=0.4, linestyle=":", linewidth=0.5)
    ax_rsi.legend(loc="upper left", fontsize=9, facecolor=ChartColors.BG,
                  edgecolor=ChartColors.GRID, labelcolor=ChartColors.TEXT,
                  prop=font)

    latest_rsi = rsi_values[-1] if rsi_values else 50
    rsi_color = ChartColors.RED if latest_rsi > 70 else (ChartColors.GREEN if latest_rsi < 30 else ChartColors.WHITE)
    ax_rsi.set_title(f"{name} ({symbol})  RSI(14): {latest_rsi:.1f}",
                     color=rsi_color, fontproperties=font, fontsize=14, pad=8, loc="left")

    plt.setp(ax_price.get_xticklabels(), visible=False)

    buf = io.BytesIO()
    fig.savefig(buf, format="rgba", dpi=dpi, facecolor=ChartColors.BG,
                edgecolor="none", pad_inches=0)
    plt.close(fig)
    buf.seek(0)
    rgba = np.frombuffer(buf.getvalue(), dtype=np.uint8)
    rgba = rgba.reshape(height_px, width_px, 4)
    return rgba


# ── Volume standalone renderer ────────────────────────────────────────────

def render_volume_standalone(
    symbol: str,
    name: str,
    kline_data: list[dict],
    width_px: int = 1440,
    height_px: int = 880,
    dpi: int = 100,
) -> np.ndarray:
    """Render volume bar chart with enhanced emphasis.

    Returns RGBA uint8 numpy array.
    """
    w_in = width_px / dpi
    h_in = height_px / dpi
    font = _make_font()

    fig = plt.figure(figsize=(w_in, h_in), dpi=dpi, facecolor=ChartColors.BG)
    gs = fig.add_gridspec(2, 1, height_ratios=[3, 2], hspace=0.03,
                          left=0.06, right=0.98, top=0.94, bottom=0.06)

    # Price line
    ax_price = fig.add_subplot(gs[0], facecolor=ChartColors.BG)
    _draw_price_overview(ax_price, kline_data, font)

    # Volume bars (enlarged)
    ax_vol = fig.add_subplot(gs[1], facecolor=ChartColors.BG, sharex=ax_price)
    if kline_data:
        payloads = [r.get("payload", {}) for r in kline_data]
        opens = [float(p.get("开盘", p.get("open", 0))) for p in payloads]
        closes = [float(p.get("收盘", p.get("close", 0))) for p in payloads]
        volumes = [float(p.get("成交量", p.get("volume", 0))) for p in payloads]
        xs = list(range(len(volumes)))

        for i, (x, o, c, v) in enumerate(zip(xs, opens, closes, volumes)):
            color = ChartColors.GREEN if c >= o else ChartColors.RED
            ax_vol.bar(x, v, width=0.7, color=color, alpha=0.8, edgecolor=color, linewidth=0.3)

        # Volume MA
        vol_arr = np.array(volumes)
        if len(vol_arr) >= 5:
            vol_ma5 = np.convolve(vol_arr, np.ones(5) / 5, mode="valid")
            ma_xs = xs[4:]
            ax_vol.plot(ma_xs, vol_ma5, color=ChartColors.YELLOW, linewidth=1.5,
                        alpha=0.8, label="VOL MA5")

        ax_vol.set_ylabel("成交量", fontsize=10, color=ChartColors.TEXT_DIM,
                          fontproperties=font)
        ax_vol.legend(loc="upper left", fontsize=9, facecolor=ChartColors.BG,
                      edgecolor=ChartColors.GRID, labelcolor=ChartColors.TEXT,
                      prop=font)

    ax_vol.set_facecolor(ChartColors.BG)
    ax_vol.tick_params(colors=ChartColors.TEXT_DIM, labelsize=9)
    for spine in ax_vol.spines.values():
        spine.set_color(ChartColors.GRID)
    ax_vol.grid(True, color=ChartColors.GRID, alpha=0.4, linestyle=":", linewidth=0.5)

    ax_vol.set_title(f"{name} ({symbol})  成交量分析",
                     color=ChartColors.WHITE, fontproperties=font, fontsize=14, pad=8, loc="left")

    plt.setp(ax_price.get_xticklabels(), visible=False)

    buf = io.BytesIO()
    fig.savefig(buf, format="rgba", dpi=dpi, facecolor=ChartColors.BG,
                edgecolor="none", pad_inches=0)
    plt.close(fig)
    buf.seek(0)
    rgba = np.frombuffer(buf.getvalue(), dtype=np.uint8)
    rgba = rgba.reshape(height_px, width_px, 4)
    return rgba


# ── Dragon-Tiger Board renderer ───────────────────────────────────────────

def render_dragon_tiger(
    title: str,
    rows: list[dict],
    width_px: int = 1440,
    height_px: int = 880,
    dpi: int = 100,
) -> np.ndarray:
    """Render dragon-tiger board as a styled table.

    Returns RGBA uint8 numpy array.
    """
    w_in = width_px / dpi
    h_in = height_px / dpi
    font = _make_font()

    fig = plt.figure(figsize=(w_in, h_in), dpi=dpi, facecolor=ChartColors.BG)
    ax = fig.add_subplot(111, facecolor=ChartColors.BG)

    if rows:
        col_labels = ["排名", "营业部", "买入(亿)", "卖出(亿)", "净额(亿)"]
        table_data = []
        for i, row in enumerate(rows[:20]):
            p = row.get("payload", row)
            table_data.append([
                str(i + 1),
                str(p.get("营业部", p.get("name", "")))[:14],
                f"{float(p.get('买入额', p.get('buy', 0))) / 1e8:.2f}",
                f"{float(p.get('卖出额', p.get('sell', 0))) / 1e8:.2f}",
                f"{float(p.get('净买入额', p.get('net', 0))) / 1e8:+.2f}",
            ])

        ax.axis("off")
        table = ax.table(
            cellText=table_data,
            colLabels=col_labels,
            cellLoc="center",
            loc="center",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(12)
        table.scale(1.0, 2.0)

        for key, cell in table.get_celld().items():
            cell.set_edgecolor(ChartColors.GRID)
            if key[0] == 0:
                cell.set_facecolor("#1a1a2e")
                cell.set_text_props(color=ChartColors.WHITE, fontproperties=font)
            else:
                cell.set_facecolor(ChartColors.BG)
                cell.set_text_props(color=ChartColors.TEXT, fontproperties=font)
                # Color net column
                if key[1] == 4:
                    val_str = cell.get_text().get_text()
                    try:
                        net_val = float(val_str)
                        cell.set_text_props(
                            color=ChartColors.GREEN if net_val >= 0 else ChartColors.RED,
                            fontproperties=font)
                    except ValueError:
                        pass
    else:
        ax.text(0.5, 0.5, "等待龙虎榜数据...", transform=ax.transAxes,
                ha="center", va="center", fontsize=20, fontproperties=font,
                color=ChartColors.TEXT_DIM)
        ax.axis("off")

    ax.set_title(title, fontsize=18, fontproperties=font,
                 color=ChartColors.WHITE, pad=15, loc="left")

    buf = io.BytesIO()
    fig.savefig(buf, format="rgba", dpi=dpi, facecolor=ChartColors.BG,
                edgecolor="none", pad_inches=0)
    plt.close(fig)
    buf.seek(0)
    rgba = np.frombuffer(buf.getvalue(), dtype=np.uint8)
    rgba = rgba.reshape(height_px, width_px, 4)
    return rgba


# ── Sector Heatmap renderer ───────────────────────────────────────────────

def render_sector_heatmap(
    title: str,
    sectors: list[dict],
    width_px: int = 1440,
    height_px: int = 880,
    dpi: int = 100,
) -> np.ndarray:
    """Render sector heatmap as horizontal bar chart.

    Returns RGBA uint8 numpy array.
    """
    w_in = width_px / dpi
    h_in = height_px / dpi
    font = _make_font()

    fig = plt.figure(figsize=(w_in, h_in), dpi=dpi, facecolor=ChartColors.BG)
    ax = fig.add_subplot(111, facecolor=ChartColors.BG)

    if sectors:
        names = []
        values = []
        for s in sectors[:25]:
            p = s.get("payload", s)
            names.append(str(p.get("板块", p.get("name", "")))[:10])
            try:
                values.append(float(p.get("涨跌幅", p.get("change", 0))))
            except (ValueError, TypeError):
                values.append(0.0)

        paired = sorted(zip(names, values), key=lambda x: abs(x[1]), reverse=True)
        names = [p[0] for p in paired]
        values = [p[1] for p in paired]

        y_pos = range(len(names))
        colors = [ChartColors.GREEN if v >= 0 else ChartColors.RED for v in values]
        bars = ax.barh(y_pos, values, color=colors, height=0.7, alpha=0.85)

        ax.set_yticks(y_pos)
        ax.set_yticklabels(names, fontproperties=font, fontsize=11, color=ChartColors.TEXT)
        ax.invert_yaxis()

        for bar, val in zip(bars, values):
            label = f" {val:+.2f}%"
            ha = "left" if val >= 0 else "right"
            offset = 0.15 if val >= 0 else -0.15
            ax.text(bar.get_width() + offset, bar.get_y() + bar.get_height() / 2,
                    label, va="center", ha=ha, fontsize=9,
                    color=ChartColors.TEXT, fontproperties=font)
    else:
        ax.text(0.5, 0.5, "等待板块数据...", transform=ax.transAxes,
                ha="center", va="center", fontsize=20, fontproperties=font,
                color=ChartColors.TEXT_DIM)
        ax.axis("off")

    ax.set_facecolor(ChartColors.BG)
    ax.tick_params(colors=ChartColors.TEXT_DIM, labelsize=11)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.axvline(x=0, color=ChartColors.TEXT_DIM, linewidth=0.8, alpha=0.5)

    ax.set_title(title, fontsize=18, fontproperties=font,
                 color=ChartColors.WHITE, pad=15, loc="left")

    buf = io.BytesIO()
    fig.savefig(buf, format="rgba", dpi=dpi, facecolor=ChartColors.BG,
                edgecolor="none", pad_inches=0)
    plt.close(fig)
    buf.seek(0)
    rgba = np.frombuffer(buf.getvalue(), dtype=np.uint8)
    rgba = rgba.reshape(height_px, width_px, 4)
    return rgba


# ── Advance/Decline renderer ──────────────────────────────────────────────

def render_advance_decline(
    title: str,
    up_count: int = 0,
    down_count: int = 0,
    flat_count: int = 0,
    limit_up: int = 0,
    limit_down: int = 0,
    width_px: int = 1440,
    height_px: int = 880,
    dpi: int = 100,
) -> np.ndarray:
    """Render advance/decline statistics as pie + bar charts.

    Returns RGBA uint8 numpy array.
    """
    w_in = width_px / dpi
    h_in = height_px / dpi
    font = _make_font()

    fig = plt.figure(figsize=(w_in, h_in), dpi=dpi, facecolor=ChartColors.BG)

    total = up_count + down_count + flat_count
    if total > 0:
        # Pie chart
        ax1 = fig.add_subplot(121, facecolor=ChartColors.BG)
        sizes = [up_count, down_count, flat_count]
        labels = [f"上涨\n{up_count}家", f"下跌\n{down_count}家", f"平盘\n{flat_count}家"]
        colors_pie = [ChartColors.GREEN, ChartColors.RED, ChartColors.TEXT_DIM]
        explode = (0.02, 0.02, 0)
        wedges, texts, autotexts = ax1.pie(
            sizes, labels=labels, colors=colors_pie, autopct="%1.1f%%",
            explode=explode, startangle=90,
            textprops={"fontproperties": font, "fontsize": 12, "color": ChartColors.WHITE},
        )
        for at in autotexts:
            at.set_fontsize(14)
            at.set_color(ChartColors.WHITE)
        ax1.set_title("涨跌分布", fontproperties=font, fontsize=16,
                      color=ChartColors.WHITE, pad=15)

        # Bar chart
        ax2 = fig.add_subplot(122, facecolor=ChartColors.BG)
        cats = ["涨停", "跌停"]
        vals = [limit_up, limit_down]
        colors_bar = [ChartColors.GREEN, ChartColors.RED]
        bars = ax2.bar(cats, vals, color=colors_bar, width=0.35, alpha=0.85, edgecolor="none")
        for bar, val in zip(bars, vals):
            ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(1, total * 0.01),
                     str(val), ha="center", va="bottom", fontsize=16,
                     color=ChartColors.WHITE, fontproperties=font, fontweight="bold")
        ax2.set_title("涨跌停家数", fontproperties=font, fontsize=16,
                      color=ChartColors.WHITE, pad=15)
        ax2.set_facecolor(ChartColors.BG)
        ax2.tick_params(colors=ChartColors.TEXT_DIM, labelsize=12)
        for spine in ax2.spines.values():
            spine.set_color(ChartColors.GRID)
        ax2.grid(True, color=ChartColors.GRID, alpha=0.3, linestyle=":", linewidth=0.5,
                 axis="y")
    else:
        ax = fig.add_subplot(111, facecolor=ChartColors.BG)
        ax.text(0.5, 0.5, "等待涨跌家数数据...", transform=ax.transAxes,
                ha="center", va="center", fontsize=20, fontproperties=font,
                color=ChartColors.TEXT_DIM)
        ax.axis("off")

    fig.suptitle(title, fontproperties=font, fontsize=18,
                 color=ChartColors.WHITE, y=0.98)

    buf = io.BytesIO()
    fig.savefig(buf, format="rgba", dpi=dpi, facecolor=ChartColors.BG,
                edgecolor="none", pad_inches=0)
    plt.close(fig)
    buf.seek(0)
    rgba = np.frombuffer(buf.getvalue(), dtype=np.uint8)
    rgba = rgba.reshape(height_px, width_px, 4)
    return rgba


# ── AI Summary card renderer ──────────────────────────────────────────────

def render_ai_summary_card(
    symbol: str,
    name: str,
    price_now: float,
    change_pct: float,
    summary_text: str,
    width_px: int = 1440,
    height_px: int = 880,
) -> np.ndarray:
    """Render AI analysis summary as a styled text card.

    Returns RGBA uint8 numpy array.
    """
    from PIL import Image, ImageDraw, ImageFont

    bg_rgb = tuple(int(ChartColors.BG.lstrip("#")[i:i+2], 16) for i in (0, 2, 4))
    img = Image.new("RGBA", (width_px, height_px), bg_rgb + (255,))
    draw = ImageDraw.Draw(img)

    try:
        if FONT_PATH:
            title_font = ImageFont.truetype(FONT_PATH, 30)
            body_font = ImageFont.truetype(FONT_PATH, 22)
            small_font = ImageFont.truetype(FONT_PATH, 16)
            icon_font = ImageFont.truetype(FONT_PATH, 40)
        else:
            title_font = body_font = small_font = icon_font = ImageFont.load_default()
    except Exception:
        title_font = body_font = small_font = icon_font = ImageFont.load_default()

    # Background card
    card_margin = 30
    draw.rounded_rectangle(
        [(card_margin, card_margin),
         (width_px - card_margin, height_px - card_margin)],
        radius=16,
        fill=(22, 27, 34, 255),
        outline=(48, 54, 61, 200),
        width=2,
    )

    # AI icon + title
    draw.text((60, 50), "🤖", font=icon_font, fill=(255, 255, 255, 255))
    draw.text((120, 55), "AI 智能分析摘要", font=title_font, fill=(88, 166, 255, 255))

    # Divider
    draw.line([(60, 105), (width_px - 60, 105)], fill=(88, 166, 255, 80), width=2)

    # Stock info
    color = (63, 185, 80, 255) if change_pct >= 0 else (248, 81, 73, 255)
    info_text = f"📊 {name} ({symbol})    {price_now:.2f}    {change_pct:+.2f}%"
    draw.text((60, 125), info_text, font=body_font, fill=color)

    # Separator
    draw.line([(60, 165), (width_px - 60, 165)], fill=(48, 54, 61, 150), width=1)

    # Summary content
    summary = summary_text or "等待 AI 分析结果生成..."
    lines = _wrap_text_pil(summary, width_px - 120, body_font, draw)

    y = 185
    for line in lines[:14]:
        # Add bullet point
        draw.text((60, y), "•", font=body_font, fill=(88, 166, 255, 200))
        draw.text((85, y), line, font=body_font, fill=(201, 209, 217, 255))
        y += 42

    # Footer
    footer_y = height_px - 60
    draw.line([(60, footer_y - 10), (width_px - 60, footer_y - 10)],
              fill=(48, 54, 61, 120), width=1)
    draw.text((60, footer_y),
              "以上分析由 AI 自动生成，仅供参考，不构成投资建议  |  StockStream AI 直播",
              font=small_font, fill=(139, 148, 158, 180))

    return np.array(img)


# ── helpers ───────────────────────────────────────────────────────────────

def _draw_price_overview(ax, kline_data: list[dict], font: FontProperties) -> None:
    """Draw compact price overview (line + MA) on given axes."""
    if not kline_data:
        return

    payloads = [r.get("payload", {}) for r in kline_data]
    closes = [float(p.get("收盘", p.get("close", 0))) for p in payloads]
    xs = list(range(len(closes)))

    # Price area fill
    ax.fill_between(xs, closes, min(closes) * 0.99,
                    color=ChartColors.BLUE + "22", alpha=0.3)

    # Up/down coloring
    if len(closes) >= 2:
        for i in range(1, len(closes)):
            seg_x = xs[i-1:i+1]
            seg_y = closes[i-1:i+1]
            color = ChartColors.GREEN if closes[i] >= closes[i-1] else ChartColors.RED
            ax.plot(seg_x, seg_y, color=color, linewidth=1.2, alpha=0.9)

    # MAs
    closes_arr = np.array(closes)
    for period, color, lw in [(5, ChartColors.MA5, 1.0), (20, ChartColors.MA20, 1.5)]:
        if len(closes_arr) >= period:
            ma = np.convolve(closes_arr, np.ones(period) / period, mode="valid")
            ma_xs = xs[period - 1:]
            ax.plot(ma_xs, ma, color=color, linewidth=lw, alpha=0.7, label=f"MA{period}")

    ax.set_facecolor(ChartColors.BG)
    ax.tick_params(colors=ChartColors.TEXT_DIM, labelsize=9)
    for spine in ax.spines.values():
        spine.set_color(ChartColors.GRID)
    ax.grid(True, color=ChartColors.GRID, alpha=0.4, linestyle=":", linewidth=0.5)
    ax.legend(loc="upper left", fontsize=8, facecolor=ChartColors.BG,
              edgecolor=ChartColors.GRID, labelcolor=ChartColors.TEXT_DIM,
              prop=font)


def _draw_macd_subplot(ax, dif: list[float], dea: list[float],
                       histogram: list[float]) -> None:
    """Draw MACD indicator on the given axes."""
    if not dif or not dea or not histogram:
        return

    xs = list(range(len(dif)))
    ax.plot(xs, dif, color=ChartColors.BLUE, linewidth=1.2, label="DIF")
    ax.plot(xs, dea, color=ChartColors.ORANGE, linewidth=1.2, label="DEA")

    for i, (x, val) in enumerate(zip(xs, histogram)):
        color = ChartColors.GREEN if val >= 0 else ChartColors.RED
        ax.bar(x, val, width=0.6, color=color, alpha=0.7)

    ax.axhline(y=0, color=ChartColors.TEXT_DIM, linewidth=0.5, linestyle="-")

    ax.set_facecolor(ChartColors.BG)
    ax.tick_params(colors=ChartColors.TEXT_DIM, labelsize=9)
    for spine in ax.spines.values():
        spine.set_color(ChartColors.GRID)
    ax.grid(True, color=ChartColors.GRID, alpha=0.4, linestyle=":", linewidth=0.5)
    ax.legend(loc="upper left", fontsize=9, facecolor=ChartColors.BG,
              edgecolor=ChartColors.GRID, labelcolor=ChartColors.TEXT)


def _wrap_text_pil(text: str, max_width: int, font, draw) -> list[str]:
    """Wrap text to fit within max_width pixels."""
    lines = []
    current = ""
    for ch in text:
        test = current + ch
        try:
            bbox = draw.textbbox((0, 0), test, font=font)
            w = bbox[2] - bbox[0]
        except Exception:
            w = len(test) * (font.size or 12) * 0.6
        if w > max_width and current:
            lines.append(current)
            current = ch
        else:
            current = test
    if current:
        lines.append(current)
    return lines or [text]
