"""Stock chart renderer — renders K-line, price, fund-flow charts as numpy RGBA arrays.

Uses matplotlib with 'Agg' backend for off-screen rendering. All charts are
returned as numpy uint8 RGBA (H, W, 4) arrays ready for overlay compositing.

Supports:
- K-line candlestick chart with MA overlays
- Price trend line chart
- Fund flow bar chart (主力/超大单/大单 净流入)
- Volume sub-chart
- Mini data panel (price, change%, turnover, etc.)
"""

from __future__ import annotations

import io
import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Force non-interactive backend before any other matplotlib import
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import FancyBboxPatch
from matplotlib.font_manager import FontProperties

# ── Chinese font discovery ──────────────────────────────────────────────

_CHINESE_FONT_CANDIDATES = [
    "SimHei", "Microsoft YaHei", "PingFang SC", "Heiti SC",
    "Noto Sans CJK SC", "WenQuanYi Micro Hei", "WenQuanYi Zen Hei",
    "Source Han Sans SC", "Arial Unicode MS", "sans-serif",
]

def _find_chinese_font() -> str:
    """Return the first available Chinese-capable font family name."""
    from matplotlib.font_manager import fontManager
    available = {f.name for f in fontManager.ttflist}
    for name in _CHINESE_FONT_CANDIDATES:
        if name in available:
            return name
    logger.warning("No Chinese font found; subtitles/charts may render as tofu (□).")
    return "sans-serif"


FONT_FAMILY = _find_chinese_font()

# ── colour palette ──────────────────────────────────────────────────────

class ChartColors:
    BG = "#0D1117"           # GitHub-dark background
    PANEL_BG = "#161B22"
    GRID = "#21262D"
    TEXT = "#C9D1D9"
    TEXT_DIM = "#8B949E"
    GREEN = "#3FB950"         # up / bullish
    RED = "#F85149"           # down / bearish
    BLUE = "#58A6FF"
    ORANGE = "#D29922"
    PURPLE = "#BC8CFF"
    YELLOW = "#E3B341"
    WHITE = "#F0F6FC"
    MA5 = "#FF6B6B"
    MA10 = "#FFA500"
    MA20 = "#9370DB"
    MA60 = "#4169E1"
    VOL_UP = "#3FB95044"
    VOL_DOWN = "#F8514944"


# ── main renderer ─────────────────────────────────────────────────────────

class StockChartRenderer:
    """Render stock market charts to numpy RGBA arrays for video compositing.

    Usage::

        renderer = StockChartRenderer(figsize=(12.8, 7.2), dpi=100)
        chart_rgba = renderer.render_kline(symbol="600519", name="贵州茅台",
                                            kline_data=rows, fund_data=rows)
        # chart_rgba.shape == (720, 1280, 4)  -- RGBA uint8
    """

    def __init__(
        self,
        figsize: tuple[float, float] = (12.8, 7.2),
        dpi: int = 100,
        facecolor: str = ChartColors.BG,
    ) -> None:
        self.figsize = figsize
        self.dpi = dpi
        self.facecolor = facecolor
        self._font = FontProperties(family=FONT_FAMILY)

    # ── public API ─────────────────────────────────────────────────

    def render_kline(
        self,
        symbol: str,
        name: str,
        kline_data: list[dict],
        fund_data: list[dict] | None = None,
        price_now: float = 0.0,
        change_pct: float = 0.0,
        highlight_latest: bool = True,
    ) -> np.ndarray:
        """Render a K-line candlestick chart with volume sub-plot.

        Args:
            symbol: Stock code e.g. "600519".
            name: Stock name e.g. "贵州茅台".
            kline_data: Daily K-line rows. Each row's payload should contain:
                date/日期, open/开盘, close/收盘, high/最高, low/最低, volume/成交量.
            fund_data: Fund flow rows for the same symbol (optional).
            price_now: Current real-time price (overrides last K-line close).
            change_pct: Current change percentage for display.
            highlight_latest: Show real-time price label.

        Returns:
            numpy uint8 RGBA array (figsize×dpi, 4 channels).
        """
        w_inches, h_inches = self.figsize
        width_px = int(w_inches * self.dpi)
        height_px = int(h_inches * self.dpi)

        fig = plt.figure(figsize=self.figsize, dpi=self.dpi, facecolor=self.facecolor)
        gs = fig.add_gridspec(4, 1, height_ratios=[3, 1, 0.5, 0.5],
                              hspace=0.05, left=0.06, right=0.98, top=0.94, bottom=0.06)

        ax_main = fig.add_subplot(gs[0], facecolor=self.facecolor)
        ax_vol = fig.add_subplot(gs[1], facecolor=self.facecolor, sharex=ax_main)
        ax_title = fig.add_subplot(gs[2], facecolor=self.facecolor)
        ax_info = fig.add_subplot(gs[3], facecolor=self.facecolor)

        self._draw_candlesticks(ax_main, ax_vol, kline_data, price_now, change_pct, highlight_latest)
        self._draw_title_bar(ax_title, symbol, name, price_now, change_pct)
        self._draw_fund_bar(ax_info, fund_data)

        # Render to numpy
        buf = io.BytesIO()
        fig.savefig(buf, format="rgba", dpi=self.dpi, facecolor=self.facecolor,
                    edgecolor="none", pad_inches=0)
        plt.close(fig)

        buf.seek(0)
        rgba = np.frombuffer(buf.getvalue(), dtype=np.uint8)
        rgba = rgba.reshape(height_px, width_px, 4)
        return rgba

    def render_price_line(
        self,
        symbol: str,
        name: str,
        data: list[dict],
        price_now: float = 0.0,
        change_pct: float = 0.0,
    ) -> np.ndarray:
        """Render a simple price-trend line chart (for intraday/minute data).

        Returns numpy uint8 RGBA array.
        """
        w_inches, h_inches = self.figsize
        width_px = int(w_inches * self.dpi)
        height_px = int(h_inches * self.dpi)

        fig = plt.figure(figsize=self.figsize, dpi=self.dpi, facecolor=self.facecolor)
        ax = fig.add_subplot(111, facecolor=self.facecolor)

        if data:
            payloads = [r.get("payload", {}) for r in data]
            times = [p.get("时间", p.get("trade_time", i)) for i, p in enumerate(payloads)]
            closes = [float(p.get("收盘", p.get("close", 0))) for p in payloads]

            if closes and len(closes) > 1:
                xs = list(range(len(closes)))
                ax.fill_between(xs, closes, min(closes) * 0.99,
                                color=ChartColors.BLUE + "33", alpha=0.3)
                ax.plot(xs, closes, color=ChartColors.BLUE, linewidth=1.5)
                ax.fill_between(xs, closes, [closes[0]] * len(closes),
                                where=np.array(closes) >= closes[0],
                                color=ChartColors.GREEN + "44", interpolate=True)
                ax.fill_between(xs, closes, [closes[0]] * len(closes),
                                where=np.array(closes) < closes[0],
                                color=ChartColors.RED + "44", interpolate=True)

        ax.set_facecolor(self.facecolor)
        ax.tick_params(colors=ChartColors.TEXT_DIM, labelsize=8)
        for spine in ax.spines.values():
            spine.set_color(ChartColors.GRID)
        ax.grid(True, color=ChartColors.GRID, alpha=0.5, linestyle=":", linewidth=0.5)

        title_str = f"{name} ({symbol})   {price_now:.2f}   {change_pct:+.2f}%"
        color = ChartColors.GREEN if change_pct >= 0 else ChartColors.RED
        ax.set_title(title_str, color=color, fontproperties=self._font, fontsize=14,
                     pad=8, loc="left")

        buf = io.BytesIO()
        fig.savefig(buf, format="rgba", dpi=self.dpi, facecolor=self.facecolor,
                    edgecolor="none", pad_inches=0)
        plt.close(fig)

        rgba = np.frombuffer(buf.getvalue(), dtype=np.uint8)
        rgba = rgba.reshape(height_px, width_px, 4)
        return rgba

    def render_fund_flow_bars(
        self,
        fund_data: list[dict],
        width_px: int = 1280,
        height_px: int = 120,
    ) -> np.ndarray:
        """Render a horizontal fund-flow bar chart as a narrow strip.

        Returns numpy uint8 RGBA array (height_px, width_px, 4).
        """
        dpi = 100
        w_in = width_px / dpi
        h_in = height_px / dpi
        fig = plt.figure(figsize=(w_in, h_in), dpi=dpi, facecolor=self.facecolor)
        ax = fig.add_subplot(111, facecolor=self.facecolor)

        if fund_data:
            payload = fund_data[-1].get("payload", {}) if fund_data else {}
            labels = ["主力净流入", "超大单", "大单", "中单", "小单"]
            keys = ["主力净流入", "超大单净流入", "大单净流入", "中单净流入", "小单净流入"]
            values = []
            for k in keys:
                v = payload.get(k, 0)
                try:
                    values.append(float(v) / 1e8)  # convert to 亿元
                except (ValueError, TypeError):
                    values.append(0.0)

            colors = [
                ChartColors.GREEN if v >= 0 else ChartColors.RED
                for v in values
            ]

            y_pos = range(len(labels))
            bars = ax.barh(y_pos, values, color=colors, height=0.6, alpha=0.85)
            ax.set_yticks(y_pos)
            ax.set_yticklabels(labels, fontproperties=self._font, fontsize=9, color=ChartColors.TEXT)
            for bar, val in zip(bars, values):
                label = f"{val:+.2f}亿"
                ax.text(bar.get_x() + bar.get_width() + (0.05 if val >= 0 else -0.05),
                        bar.get_y() + bar.get_height() / 2, label,
                        va="center", ha="left" if val >= 0 else "right",
                        fontsize=8, color=ChartColors.TEXT, fontproperties=self._font)

        ax.set_facecolor(self.facecolor)
        ax.tick_params(colors=ChartColors.TEXT_DIM, labelsize=9)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.axvline(x=0, color=ChartColors.TEXT_DIM, linewidth=0.5, alpha=0.5)
        ax.invert_yaxis()

        buf = io.BytesIO()
        fig.savefig(buf, format="rgba", dpi=dpi, facecolor=self.facecolor,
                    edgecolor="none", pad_inches=0)
        plt.close(fig)

        buf.seek(0)
        rgba = np.frombuffer(buf.getvalue(), dtype=np.uint8)

        # Handle potential size mismatch from matplotlib rounding
        expected = height_px * width_px * 4
        actual = rgba.size
        if actual != expected:
            # Fallback: determine actual dimensions from data
            actual_pixels = actual // 4
            actual_h = int(actual_pixels / width_px) if width_px > 0 else height_px
            actual_w = int(actual_pixels / actual_h) if actual_h > 0 else width_px
            # Trim or pad
            if actual_pixels >= height_px * width_px:
                rgba = rgba[:expected]
            else:
                padded = np.zeros(expected, dtype=np.uint8)
                padded[:actual] = rgba
                rgba = padded

        rgba = rgba.reshape(height_px, width_px, 4)
        return rgba

    # ── internal drawing helpers ────────────────────────────────────

    def _draw_candlesticks(
        self,
        ax_main,
        ax_vol,
        data: list[dict],
        price_now: float,
        change_pct: float,
        highlight: bool,
    ) -> None:
        """Draw K-line candlesticks + MA lines + volume bars."""
        if not data:
            return

        payloads = [r.get("payload", {}) for r in data]
        dates = [p.get("日期", p.get("date", str(i))) for i, p in enumerate(payloads)]
        opens = [float(p.get("开盘", p.get("open", 0))) for p in payloads]
        closes = [float(p.get("收盘", p.get("close", 0))) for p in payloads]
        highs = [float(p.get("最高", p.get("high", 0))) for p in payloads]
        lows = [float(p.get("最低", p.get("low", 0))) for p in payloads]
        volumes = [float(p.get("成交量", p.get("volume", 0))) for p in payloads]

        xs = list(range(len(dates)))
        width = 0.6

        # ── candlesticks ──
        for i, (x, o, c, h, l) in enumerate(zip(xs, opens, closes, highs, lows)):
            color = ChartColors.GREEN if c >= o else ChartColors.RED
            body_h = abs(c - o)
            body_bottom = min(c, o)
            # Wick
            ax_main.plot([x, x], [l, h], color=color, linewidth=0.8, solid_capstyle="round")
            # Body
            if body_h > 0:
                ax_main.add_patch(plt.Rectangle(
                    (x - width / 2, body_bottom), width, body_h,
                    facecolor=color, edgecolor=color, linewidth=0.5, alpha=0.9,
                ))
            else:
                ax_main.plot(x, c, marker="_", color=color, markersize=8)

        # ── MA lines ──
        closes_arr = np.array(closes)
        for period, color, lw in [(5, ChartColors.MA5, 1.0), (10, ChartColors.MA10, 1.0),
                                   (20, ChartColors.MA20, 1.5), (60, ChartColors.MA60, 1.5)]:
            if len(closes_arr) >= period:
                ma = np.convolve(closes_arr, np.ones(period) / period, mode="valid")
                ma_xs = xs[period - 1:]
                ax_main.plot(ma_xs, ma, color=color, linewidth=lw, alpha=0.8,
                             label=f"MA{period}")
        ax_main.legend(loc="upper left", fontsize=7, facecolor=ChartColors.BG + "88",
                       edgecolor=ChartColors.GRID, labelcolor=ChartColors.TEXT_DIM,
                       prop=self._font)

        # ── highlight latest price ──
        if highlight and price_now > 0:
            ax_main.axhline(y=price_now, color=ChartColors.YELLOW, linewidth=0.8,
                            linestyle="--", alpha=0.6)
            last_x = xs[-1] if xs else 0
            ax_main.annotate(
                f"  {price_now:.2f} ({change_pct:+.2f}%)",
                xy=(last_x, price_now),
                fontsize=9, color=ChartColors.WHITE,
                fontproperties=self._font,
                bbox=dict(boxstyle="round,pad=0.3", facecolor=(
                    ChartColors.GREEN if change_pct >= 0 else ChartColors.RED)),
            )

        # ── volume bars ──
        for i, (x, o, c, v) in enumerate(zip(xs, opens, closes, volumes)):
            color = ChartColors.VOL_UP if c >= o else ChartColors.VOL_DOWN
            ax_vol.bar(x, v, width=width * 0.8, color=color, edgecolor=color, linewidth=0.3)

        # ── styling ──
        for ax in (ax_main, ax_vol):
            ax.set_facecolor(self.facecolor)
            ax.tick_params(colors=ChartColors.TEXT_DIM, labelsize=8)
            for spine in ax.spines.values():
                spine.set_color(ChartColors.GRID)
            ax.grid(True, color=ChartColors.GRID, alpha=0.4, linestyle=":", linewidth=0.5)
        ax_vol.set_ylabel("VOL", fontsize=7, color=ChartColors.TEXT_DIM, fontproperties=self._font)

        # Format x-axis labels
        if len(dates) > 20:
            tick_step = max(1, len(dates) // 8)
            tick_xs = xs[::tick_step]
            tick_labels = [str(d)[4:8] if len(str(d)) > 6 else str(d) for d in dates[::tick_step]]
            ax_vol.set_xticks(tick_xs)
            ax_vol.set_xticklabels(tick_labels, fontsize=7, rotation=0)
        else:
            ax_vol.set_xticks(xs)
            ax_vol.set_xticklabels([str(d)[4:8] if len(str(d)) > 6 else str(d) for d in dates],
                                   fontsize=7, rotation=0)

        plt.setp(ax_main.get_xticklabels(), visible=False)

    def _draw_title_bar(
        self,
        ax,
        symbol: str,
        name: str,
        price_now: float,
        change_pct: float,
    ) -> None:
        """Draw a compact title bar with stock info."""
        ax.set_facecolor(ChartColors.PANEL_BG)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)

        color = ChartColors.GREEN if change_pct >= 0 else ChartColors.RED
        text = f"  {name} ({symbol})    {price_now:.2f}    {change_pct:+.2f}%"
        ax.text(0.02, 0.5, text, transform=ax.transAxes, fontsize=13,
                fontproperties=self._font, color=ChartColors.WHITE, va="center",
                bbox=dict(facecolor=color, alpha=0.2, edgecolor=color, linewidth=1,
                          boxstyle="round,pad=0.4"))

    def _draw_fund_bar(self, ax, fund_data: list[dict] | None) -> None:
        """Draw a compact fund-flow bar strip."""
        ax.set_facecolor(ChartColors.PANEL_BG)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)

        if not fund_data:
            ax.text(0.5, 0.5, "等待资金流向数据...", transform=ax.transAxes,
                    ha="center", va="center", fontsize=10, fontproperties=self._font,
                    color=ChartColors.TEXT_DIM)
            return

        payload = fund_data[-1].get("payload", {}) if fund_data else {}
        items = [
            ("主力净流入", "主力净流入"),
            ("超大单", "超大单净流入"),
            ("大单", "大单净流入"),
        ]
        x_pos = 0.05
        for label, key in items:
            try:
                val = float(payload.get(key, 0)) / 1e4  # 万元
            except (ValueError, TypeError):
                val = 0.0
            color = ChartColors.GREEN if val >= 0 else ChartColors.RED
            ax.text(x_pos, 0.5, f"{label} {val:+.0f}万", transform=ax.transAxes,
                    fontsize=10, fontproperties=self._font,
                    color=color, va="center",
                    bbox=dict(facecolor=color, alpha=0.15, edgecolor=color, linewidth=0.5,
                              boxstyle="round,pad=0.3"))
            x_pos += 0.3
