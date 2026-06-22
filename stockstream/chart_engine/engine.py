"""Chart Engine — asynchronous chart rendering with PNG file caching.

Generates 7 chart types via matplotlib/plotly, saves PNGs to cache/charts/,
and refreshes every 5 seconds.  Public API: get_chart(stock_code, chart_type).

Architecture:
    ┌──────────────┐     ┌──────────────────┐     ┌───────────────────┐
    │  get_chart() │────▶│  _cache_lookup    │────▶│  return PNG path  │
    │  (async)     │     │  (stale check)    │     │                   │
    └──────┬───────┘     └────────┬─────────┘     └───────────────────┘
           │                      │ cache miss / stale
           ▼                      ▼
    ┌──────────────┐     ┌──────────────────┐
    │ MarketSQLite │────▶│  _render_*()     │──▶ cache/charts/*.png
    │ Storage      │     │  (matplotlib)    │
    └──────────────┘     └──────────────────┘
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── matplotlib setup ──────────────────────────────────────────────────────
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties

# ── Chinese font ──────────────────────────────────────────────────────────
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

FONT_FAMILY = _find_chinese_font()


# ── colour palette (matching chart_renderer.py) ──────────────────────────

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
    MA5 = "#FF6B6B"
    MA10 = "#FFA500"
    MA20 = "#9370DB"
    MA60 = "#4169E1"


# ── imports from sibling modules ──────────────────────────────────────────

from stockstream.chart_engine.models import ChartRequest, ChartResult, ChartType
from stockstream.market.models import MarketDataset
from stockstream.market.storage import MarketSQLiteStorage


class ChartEngine:
    """Async chart engine with file-cache based PNG generation.

    Usage::

        engine = ChartEngine(storage=market_storage, cache_dir="cache/charts")
        result = await engine.get_chart("600519", ChartType.DAILY_KLINE)
        # result.file_path → "cache/charts/600519_daily_kline.png"
    """

    def __init__(
        self,
        storage: MarketSQLiteStorage,
        cache_dir: str = "cache/charts",
        refresh_seconds: int = 5,
        default_width: int = 1440,
        default_height: int = 880,
        default_dpi: int = 100,
    ) -> None:
        self.storage = storage
        self.cache_dir = Path(cache_dir)
        self.refresh_seconds = refresh_seconds
        self.default_width = default_width
        self.default_height = default_height
        self.default_dpi = default_dpi

        self._font = FontProperties(family=FONT_FAMILY)
        self._lock = asyncio.Lock()  # prevent concurrent renders for same key
        self._last_render: dict[str, float] = {}  # key → timestamp

        # Ensure cache directory exists
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ── public API ──────────────────────────────────────────────────────

    async def get_chart(
        self,
        stock_code: str,
        chart_type: ChartType,
        *,
        width_px: int | None = None,
        height_px: int | None = None,
        dpi: int | None = None,
        force_refresh: bool = False,
    ) -> ChartResult:
        """Return the latest chart PNG for a stock + chart type.

        If the cached PNG is younger than *refresh_seconds*, returns it
        directly.  Otherwise re-renders from the latest market data.

        Args:
            stock_code: Stock code (e.g. "600519").
            chart_type: One of ChartType enum values.
            width_px: Override default chart width.
            height_px: Override default chart height.
            dpi: Override default DPI.
            force_refresh: Bypass cache and force re-render.

        Returns:
            ChartResult with file_path and optional png_data.
        """
        stock_code = stock_code.strip().upper()
        w = width_px or self.default_width
        h = height_px or self.default_height
        d = dpi or self.default_dpi
        cache_key = f"{stock_code}_{chart_type.value}"

        # Fast path: cache hit
        if not force_refresh and self._is_cache_fresh(cache_key):
            png_path = self._png_path(stock_code, chart_type)
            if png_path.exists():
                return ChartResult(
                    stock_code=stock_code,
                    chart_type=chart_type,
                    file_path=str(png_path.resolve()),
                    width_px=w,
                    height_px=h,
                )

        # Render under lock to avoid concurrent renders for same key
        async with self._lock:
            # Double-check after acquiring lock
            if not force_refresh and self._is_cache_fresh(cache_key):
                png_path = self._png_path(stock_code, chart_type)
                if png_path.exists():
                    return ChartResult(
                        stock_code=stock_code,
                        chart_type=chart_type,
                        file_path=str(png_path.resolve()),
                        width_px=w,
                        height_px=h,
                    )

            return await self._render_and_cache(
                stock_code, chart_type, w, h, d, cache_key
            )

    async def get_chart_png_bytes(
        self,
        stock_code: str,
        chart_type: ChartType,
        *,
        width_px: int | None = None,
        height_px: int | None = None,
        dpi: int | None = None,
        force_refresh: bool = False,
    ) -> bytes | None:
        """Convenience: return raw PNG bytes instead of a file path."""
        result = await self.get_chart(
            stock_code, chart_type,
            width_px=width_px, height_px=height_px, dpi=dpi,
            force_refresh=force_refresh,
        )
        if result.success:
            return Path(result.file_path).read_bytes() if result.png_data is None else result.png_data
        return None

    async def refresh_all(self, stock_code: str) -> list[ChartResult]:
        """Force-refresh all 7 chart types for a given stock."""
        results = []
        for ct in ChartType:
            result = await self.get_chart(stock_code, ct, force_refresh=True)
            results.append(result)
        return results

    async def list_cache(self) -> list[dict[str, Any]]:
        """List all cached chart files with metadata."""
        entries = []
        for p in sorted(self.cache_dir.glob("*.png")):
            stat = p.stat()
            entries.append({
                "file": p.name,
                "size_bytes": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            })
        return entries

    async def clear_cache(self, stock_code: str | None = None) -> int:
        """Delete cached PNGs.  If stock_code is given, only delete that stock's."""
        if stock_code:
            pattern = f"{stock_code.upper()}_*.png"
        else:
            pattern = "*.png"
        deleted = 0
        for p in self.cache_dir.glob(pattern):
            p.unlink()
            deleted += 1
        self._last_render.clear()
        logger.info("Cleared %d cached chart(s) matching %s", deleted, pattern)
        return deleted

    # ── internal: cache logic ────────────────────────────────────────────

    def _png_path(self, stock_code: str, chart_type: ChartType) -> Path:
        return self.cache_dir / f"{stock_code}_{chart_type.value}.png"

    def _is_cache_fresh(self, cache_key: str) -> bool:
        last = self._last_render.get(cache_key, 0)
        return (time.monotonic() - last) < self.refresh_seconds

    async def _render_and_cache(
        self,
        stock_code: str,
        chart_type: ChartType,
        width_px: int,
        height_px: int,
        dpi: int,
        cache_key: str,
    ) -> ChartResult:
        """Fetch data → render → save PNG → return result."""
        png_path = self._png_path(stock_code, chart_type)
        start = time.monotonic()

        try:
            rgba = await self._render_chart(stock_code, chart_type, width_px, height_px, dpi)
        except Exception as exc:
            logger.exception("Chart render failed %s/%s: %s", stock_code, chart_type.value, exc)
            return ChartResult(
                stock_code=stock_code,
                chart_type=chart_type,
                file_path="",
                error=str(exc),
                width_px=width_px,
                height_px=height_px,
            )

        if rgba is None or rgba.size == 0:
            return ChartResult(
                stock_code=stock_code,
                chart_type=chart_type,
                file_path="",
                error="No data available",
                width_px=width_px,
                height_px=height_px,
            )

        # Convert RGBA → PNG bytes
        from PIL import Image
        img = Image.fromarray(rgba, mode="RGBA")
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        png_bytes = buf.getvalue()

        # Write to disk atomically
        tmp_path = png_path.with_suffix(".tmp")
        tmp_path.write_bytes(png_bytes)
        tmp_path.replace(png_path)

        self._last_render[cache_key] = time.monotonic()
        elapsed = (time.monotonic() - start) * 1000
        logger.debug("Rendered %s/%s → %s (%.0f ms, %d bytes)",
                     stock_code, chart_type.value, png_path.name, elapsed, len(png_bytes))

        return ChartResult(
            stock_code=stock_code,
            chart_type=chart_type,
            file_path=str(png_path.resolve()),
            png_data=png_bytes,
            width_px=width_px,
            height_px=height_px,
        )

    # ── internal: data fetching ──────────────────────────────────────────

    async def _fetch_kline_data(
        self, stock_code: str, dataset: MarketDataset, limit: int = 200
    ) -> list[dict]:
        """Fetch K-line rows from market storage."""
        try:
            return await self.storage.symbol_history(
                dataset=dataset, symbol=stock_code, limit=limit,
            )
        except Exception as exc:
            logger.warning("Failed to fetch %s for %s: %s", dataset.value, stock_code, exc)
            return []

    async def _fetch_fund_data(self, stock_code: str, limit: int = 100) -> list[dict]:
        return await self._fetch_kline_data(stock_code, MarketDataset.FUND_FLOW, limit)

    async def _fetch_spot_data(self, stock_code: str) -> dict | None:
        """Fetch latest spot quote for a stock."""
        try:
            rows = await self.storage.symbol_history(
                dataset=MarketDataset.SPOT, symbol=stock_code, limit=1,
            )
            if rows:
                return rows[-1].get("payload", {})
        except Exception:
            pass
        return None

    # ── internal: chart rendering ────────────────────────────────────────

    async def _render_chart(
        self,
        stock_code: str,
        chart_type: ChartType,
        width_px: int,
        height_px: int,
        dpi: int,
    ) -> np.ndarray | None:
        """Dispatch to the appropriate renderer."""
        renderer_map = {
            ChartType.DAILY_KLINE: self._render_daily_kline,
            ChartType.MINUTE60_KLINE: self._render_minute60_kline,
            ChartType.INTRADAY: self._render_intraday,
            ChartType.MACD: self._render_macd,
            ChartType.RSI: self._render_rsi,
            ChartType.VOLUME: self._render_volume,
            ChartType.FUND_FLOW: self._render_fund_flow,
        }
        fn = renderer_map.get(chart_type)
        if fn is None:
            raise ValueError(f"Unknown chart type: {chart_type}")
        return await fn(stock_code, width_px, height_px, dpi)

    # ── 1. Daily K-line ────────────────────────────────────────────────

    async def _render_daily_kline(
        self, stock_code: str, w: int, h: int, dpi: int,
    ) -> np.ndarray | None:
        kline = await self._fetch_kline_data(stock_code, MarketDataset.DAILY, limit=200)
        if not kline:
            return None
        fund = await self._fetch_fund_data(stock_code, limit=50)
        spot = await self._fetch_spot_data(stock_code)
        price_now = float(spot.get("最新价", spot.get("price", 0))) if spot else 0.0
        change_pct = float(spot.get("涨跌幅", spot.get("change_pct", 0))) if spot else 0.0
        name = spot.get("名称", stock_code) if spot else stock_code

        w_in, h_in = w / dpi, h / dpi
        fig = plt.figure(figsize=(w_in, h_in), dpi=dpi, facecolor=C.BG)
        gs = fig.add_gridspec(4, 1, height_ratios=[3, 1, 0.5, 0.5],
                              hspace=0.05, left=0.06, right=0.98, top=0.94, bottom=0.06)
        ax_main = fig.add_subplot(gs[0], facecolor=C.BG)
        ax_vol = fig.add_subplot(gs[1], facecolor=C.BG, sharex=ax_main)
        ax_title = fig.add_subplot(gs[2], facecolor=C.PANEL_BG)
        ax_info = fig.add_subplot(gs[3], facecolor=C.PANEL_BG)

        self._draw_candlesticks(ax_main, ax_vol, kline, price_now, change_pct)
        self._draw_title_bar(ax_title, stock_code, name, price_now, change_pct)
        self._draw_fund_strip(ax_info, fund)

        buf = io.BytesIO()
        fig.savefig(buf, format="rgba", dpi=dpi, facecolor=C.BG, edgecolor="none", pad_inches=0)
        plt.close(fig)
        buf.seek(0)
        return np.frombuffer(buf.getvalue(), dtype=np.uint8).reshape(h, w, 4)

    # ── 2. 60-minute K-line ────────────────────────────────────────────

    async def _render_minute60_kline(
        self, stock_code: str, w: int, h: int, dpi: int,
    ) -> np.ndarray | None:
        kline = await self._fetch_kline_data(stock_code, MarketDataset.MINUTE_60, limit=200)
        if not kline:
            return None
        spot = await self._fetch_spot_data(stock_code)
        price_now = float(spot.get("最新价", spot.get("price", 0))) if spot else 0.0
        change_pct = float(spot.get("涨跌幅", spot.get("change_pct", 0))) if spot else 0.0
        name = spot.get("名称", stock_code) if spot else stock_code

        w_in, h_in = w / dpi, h / dpi
        fig = plt.figure(figsize=(w_in, h_in), dpi=dpi, facecolor=C.BG)
        gs = fig.add_gridspec(4, 1, height_ratios=[3, 1, 0.5, 0.5],
                              hspace=0.05, left=0.06, right=0.98, top=0.94, bottom=0.06)
        ax_main = fig.add_subplot(gs[0], facecolor=C.BG)
        ax_vol = fig.add_subplot(gs[1], facecolor=C.BG, sharex=ax_main)
        ax_title = fig.add_subplot(gs[2], facecolor=C.PANEL_BG)
        ax_blank = fig.add_subplot(gs[3], facecolor=C.PANEL_BG)

        self._draw_candlesticks(ax_main, ax_vol, kline, price_now, change_pct)
        self._draw_title_bar(ax_title, stock_code, name, price_now, change_pct)
        ax_blank.set_facecolor(C.PANEL_BG)
        ax_blank.set_xticks([]); ax_blank.set_yticks([])
        for sp in ax_blank.spines.values():
            sp.set_visible(False)
        ax_blank.text(0.5, 0.5, "60分钟K线", transform=ax_blank.transAxes,
                      ha="center", va="center", fontsize=10, fontproperties=self._font,
                      color=C.TEXT_DIM)

        buf = io.BytesIO()
        fig.savefig(buf, format="rgba", dpi=dpi, facecolor=C.BG, edgecolor="none", pad_inches=0)
        plt.close(fig)
        buf.seek(0)
        return np.frombuffer(buf.getvalue(), dtype=np.uint8).reshape(h, w, 4)

    # ── 3. Intraday price line ─────────────────────────────────────────

    async def _render_intraday(
        self, stock_code: str, w: int, h: int, dpi: int,
    ) -> np.ndarray | None:
        kline = await self._fetch_kline_data(stock_code, MarketDataset.MINUTE_60, limit=200)
        if not kline:
            return None
        spot = await self._fetch_spot_data(stock_code)
        price_now = float(spot.get("最新价", spot.get("price", 0))) if spot else 0.0
        change_pct = float(spot.get("涨跌幅", spot.get("change_pct", 0))) if spot else 0.0
        name = spot.get("名称", stock_code) if spot else stock_code

        payloads = [r.get("payload", {}) for r in kline]
        closes = [float(p.get("收盘", p.get("close", 0))) for p in payloads]
        xs = list(range(len(closes)))

        w_in, h_in = w / dpi, h / dpi
        fig = plt.figure(figsize=(w_in, h_in), dpi=dpi, facecolor=C.BG)
        ax = fig.add_subplot(111, facecolor=C.BG)

        if closes:
            ax.fill_between(xs, closes, min(closes) * 0.99, color=C.BLUE + "33", alpha=0.3)
            ax.plot(xs, closes, color=C.BLUE, linewidth=1.8)
            if len(closes) >= 5:
                ma5 = np.convolve(np.array(closes), np.ones(5)/5, mode="valid")
                ax.plot(xs[4:], ma5, color=C.MA5, linewidth=1.0, alpha=0.8, label="MA5")

        ax.set_facecolor(C.BG)
        ax.tick_params(colors=C.TEXT_DIM, labelsize=8)
        for sp in ax.spines.values():
            sp.set_color(C.GRID)
        ax.grid(True, color=C.GRID, alpha=0.5, linestyle=":", linewidth=0.5)
        ax.legend(loc="upper left", fontsize=8, facecolor=C.BG, edgecolor=C.GRID,
                  labelcolor=C.TEXT_DIM, prop=self._font)

        title_str = f"{name} ({stock_code})  分时图   {price_now:.2f}   {change_pct:+.2f}%"
        color = C.GREEN if change_pct >= 0 else C.RED
        ax.set_title(title_str, color=color, fontproperties=self._font, fontsize=14, pad=8, loc="left")

        buf = io.BytesIO()
        fig.savefig(buf, format="rgba", dpi=dpi, facecolor=C.BG, edgecolor="none", pad_inches=0)
        plt.close(fig)
        buf.seek(0)
        return np.frombuffer(buf.getvalue(), dtype=np.uint8).reshape(h, w, 4)

    # ── 4. MACD ────────────────────────────────────────────────────────

    async def _render_macd(
        self, stock_code: str, w: int, h: int, dpi: int,
    ) -> np.ndarray | None:
        kline = await self._fetch_kline_data(stock_code, MarketDataset.DAILY, limit=200)
        if not kline or len(kline) < 26:
            return None
        spot = await self._fetch_spot_data(stock_code)
        name = spot.get("名称", stock_code) if spot else stock_code

        payloads = [r.get("payload", {}) for r in kline]
        closes = [float(p.get("收盘", p.get("close", 0))) for p in payloads]

        dif, dea, histogram = self._compute_macd(closes)

        w_in, h_in = w / dpi, h / dpi
        fig = plt.figure(figsize=(w_in, h_in), dpi=dpi, facecolor=C.BG)
        gs = fig.add_gridspec(3, 1, height_ratios=[2, 1, 1], hspace=0.05,
                              left=0.06, right=0.98, top=0.94, bottom=0.06)

        # Price sub-plot
        ax_price = fig.add_subplot(gs[0], facecolor=C.BG)
        xs = list(range(len(closes)))
        ax_price.fill_between(xs, closes, min(closes) * 0.99, color=C.BLUE + "22", alpha=0.3)
        for i in range(1, len(closes)):
            seg_x = xs[i-1:i+1]; seg_y = closes[i-1:i+1]
            color = C.GREEN if closes[i] >= closes[i-1] else C.RED
            ax_price.plot(seg_x, seg_y, color=color, linewidth=1.0, alpha=0.9)
        ax_price.set_facecolor(C.BG)
        ax_price.tick_params(colors=C.TEXT_DIM, labelsize=9)
        for sp in ax_price.spines.values():
            sp.set_color(C.GRID)
        ax_price.grid(True, color=C.GRID, alpha=0.4, linestyle=":", linewidth=0.5)

        # MACD sub-plot
        ax_macd = fig.add_subplot(gs[1], facecolor=C.BG, sharex=ax_price)
        macd_xs = list(range(len(dif)))
        ax_macd.plot(macd_xs, dif, color=C.BLUE, linewidth=1.2, label="DIF")
        ax_macd.plot(macd_xs, dea, color=C.ORANGE, linewidth=1.2, label="DEA")
        for i, val in enumerate(histogram):
            bar_color = C.GREEN if val >= 0 else C.RED
            ax_macd.bar(macd_xs[i], val, width=0.6, color=bar_color, alpha=0.7)
        ax_macd.axhline(y=0, color=C.TEXT_DIM, linewidth=0.5)
        ax_macd.set_facecolor(C.BG)
        ax_macd.tick_params(colors=C.TEXT_DIM, labelsize=9)
        for sp in ax_macd.spines.values():
            sp.set_color(C.GRID)
        ax_macd.grid(True, color=C.GRID, alpha=0.4, linestyle=":", linewidth=0.5)
        ax_macd.legend(loc="upper left", fontsize=9, facecolor=C.BG,
                       edgecolor=C.GRID, labelcolor=C.TEXT, prop=self._font)

        # Info bar
        ax_info = fig.add_subplot(gs[2], facecolor=C.PANEL_BG)
        ax_info.set_xticks([]); ax_info.set_yticks([])
        for sp in ax_info.spines.values():
            sp.set_visible(False)
        latest_dif = dif[-1] if dif else 0
        latest_dea = dea[-1] if dea else 0
        latest_hist = histogram[-1] if histogram else 0
        h_color = C.GREEN if latest_hist >= 0 else C.RED
        ax_info.text(0.02, 0.5, f"  {name} ({stock_code})  MACD  |  "
                     f"DIF: {latest_dif:.3f}  DEA: {latest_dea:.3f}  柱: {latest_hist:+.3f}",
                     transform=ax_info.transAxes, fontsize=13, fontproperties=self._font,
                     color=C.WHITE, va="center",
                     bbox=dict(facecolor=h_color, alpha=0.2, edgecolor=h_color,
                               linewidth=1, boxstyle="round,pad=0.4"))

        plt.setp(ax_price.get_xticklabels(), visible=False)
        plt.setp(ax_macd.get_xticklabels(), visible=False)

        buf = io.BytesIO()
        fig.savefig(buf, format="rgba", dpi=dpi, facecolor=C.BG, edgecolor="none", pad_inches=0)
        plt.close(fig)
        buf.seek(0)
        return np.frombuffer(buf.getvalue(), dtype=np.uint8).reshape(h, w, 4)

    # ── 5. RSI ─────────────────────────────────────────────────────────

    async def _render_rsi(
        self, stock_code: str, w: int, h: int, dpi: int,
    ) -> np.ndarray | None:
        kline = await self._fetch_kline_data(stock_code, MarketDataset.DAILY, limit=200)
        if not kline or len(kline) < 15:
            return None
        spot = await self._fetch_spot_data(stock_code)
        name = spot.get("名称", stock_code) if spot else stock_code

        payloads = [r.get("payload", {}) for r in kline]
        closes = [float(p.get("收盘", p.get("close", 0))) for p in payloads]
        rsi_vals = self._compute_rsi(closes, period=14)

        w_in, h_in = w / dpi, h / dpi
        fig = plt.figure(figsize=(w_in, h_in), dpi=dpi, facecolor=C.BG)
        gs = fig.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.05,
                              left=0.06, right=0.98, top=0.94, bottom=0.06)

        # Price overview
        ax_price = fig.add_subplot(gs[0], facecolor=C.BG)
        xs = list(range(len(closes)))
        ax_price.fill_between(xs, closes, min(closes) * 0.99, color=C.BLUE + "22", alpha=0.3)
        for i in range(1, len(closes)):
            seg_x = xs[i-1:i+1]; seg_y = closes[i-1:i+1]
            color = C.GREEN if closes[i] >= closes[i-1] else C.RED
            ax_price.plot(seg_x, seg_y, color=color, linewidth=1.0, alpha=0.9)
        ax_price.set_facecolor(C.BG)
        ax_price.tick_params(colors=C.TEXT_DIM, labelsize=9)
        for sp in ax_price.spines.values():
            sp.set_color(C.GRID)
        ax_price.grid(True, color=C.GRID, alpha=0.4, linestyle=":", linewidth=0.5)

        # RSI sub-plot
        ax_rsi = fig.add_subplot(gs[1], facecolor=C.BG, sharex=ax_price)
        rsi_xs = list(range(len(rsi_vals)))
        ax_rsi.plot(rsi_xs, rsi_vals, color=C.PURPLE, linewidth=1.8, label="RSI(14)")
        ax_rsi.fill_between(rsi_xs, rsi_vals, 50,
                            where=np.array(rsi_vals) >= 50,
                            color=C.GREEN + "22", alpha=0.3)
        ax_rsi.fill_between(rsi_xs, rsi_vals, 50,
                            where=np.array(rsi_vals) < 50,
                            color=C.RED + "22", alpha=0.3)
        ax_rsi.axhline(y=70, color=C.RED, linewidth=1.0, linestyle="--", alpha=0.7)
        ax_rsi.axhline(y=30, color=C.GREEN, linewidth=1.0, linestyle="--", alpha=0.7)
        ax_rsi.axhline(y=50, color=C.TEXT_DIM, linewidth=0.5, linestyle=":", alpha=0.4)
        ax_rsi.set_ylim(0, 100)
        ax_rsi.axhspan(70, 100, alpha=0.06, color=C.RED)
        ax_rsi.axhspan(0, 30, alpha=0.06, color=C.GREEN)
        ax_rsi.text(0.99, 0.92, "超买区 70", transform=ax_rsi.transAxes,
                    ha="right", fontsize=9, color=C.RED, fontproperties=self._font)
        ax_rsi.text(0.99, 0.08, "超卖区 30", transform=ax_rsi.transAxes,
                    ha="right", fontsize=9, color=C.GREEN, fontproperties=self._font)
        ax_rsi.set_facecolor(C.BG)
        ax_rsi.tick_params(colors=C.TEXT_DIM, labelsize=9)
        for sp in ax_rsi.spines.values():
            sp.set_color(C.GRID)
        ax_rsi.grid(True, color=C.GRID, alpha=0.4, linestyle=":", linewidth=0.5)
        ax_rsi.legend(loc="upper left", fontsize=9, facecolor=C.BG,
                      edgecolor=C.GRID, labelcolor=C.TEXT, prop=self._font)

        latest_rsi = rsi_vals[-1] if rsi_vals else 50
        rsi_color = C.RED if latest_rsi > 70 else (C.GREEN if latest_rsi < 30 else C.WHITE)
        ax_rsi.set_title(f"{name} ({stock_code})  RSI(14): {latest_rsi:.1f}",
                         color=rsi_color, fontproperties=self._font, fontsize=14, pad=8, loc="left")

        plt.setp(ax_price.get_xticklabels(), visible=False)

        buf = io.BytesIO()
        fig.savefig(buf, format="rgba", dpi=dpi, facecolor=C.BG, edgecolor="none", pad_inches=0)
        plt.close(fig)
        buf.seek(0)
        return np.frombuffer(buf.getvalue(), dtype=np.uint8).reshape(h, w, 4)

    # ── 6. Volume ──────────────────────────────────────────────────────

    async def _render_volume(
        self, stock_code: str, w: int, h: int, dpi: int,
    ) -> np.ndarray | None:
        kline = await self._fetch_kline_data(stock_code, MarketDataset.DAILY, limit=200)
        if not kline:
            return None
        spot = await self._fetch_spot_data(stock_code)
        name = spot.get("名称", stock_code) if spot else stock_code

        payloads = [r.get("payload", {}) for r in kline]
        opens = [float(p.get("开盘", p.get("open", 0))) for p in payloads]
        closes = [float(p.get("收盘", p.get("close", 0))) for p in payloads]
        volumes = [float(p.get("成交量", p.get("volume", 0))) for p in payloads]
        xs = list(range(len(volumes)))

        w_in, h_in = w / dpi, h / dpi
        fig = plt.figure(figsize=(w_in, h_in), dpi=dpi, facecolor=C.BG)
        gs = fig.add_gridspec(2, 1, height_ratios=[3, 2], hspace=0.03,
                              left=0.06, right=0.98, top=0.94, bottom=0.06)

        # Price line
        ax_price = fig.add_subplot(gs[0], facecolor=C.BG)
        ax_price.fill_between(xs, closes, min(closes) * 0.99, color=C.BLUE + "22", alpha=0.3)
        for i in range(1, len(closes)):
            seg_x = xs[i-1:i+1]; seg_y = closes[i-1:i+1]
            color = C.GREEN if closes[i] >= closes[i-1] else C.RED
            ax_price.plot(seg_x, seg_y, color=color, linewidth=1.0, alpha=0.9)
        if len(closes) >= 5:
            ma5 = np.convolve(np.array(closes), np.ones(5)/5, mode="valid")
            ax_price.plot(xs[4:], ma5, color=C.MA5, linewidth=1.0, alpha=0.7, label="MA5")
        ax_price.set_facecolor(C.BG)
        ax_price.tick_params(colors=C.TEXT_DIM, labelsize=9)
        for sp in ax_price.spines.values():
            sp.set_color(C.GRID)
        ax_price.grid(True, color=C.GRID, alpha=0.4, linestyle=":", linewidth=0.5)
        ax_price.legend(loc="upper left", fontsize=8, facecolor=C.BG,
                        edgecolor=C.GRID, labelcolor=C.TEXT_DIM, prop=self._font)

        # Volume bars
        ax_vol = fig.add_subplot(gs[1], facecolor=C.BG, sharex=ax_price)
        for i, (x_val, o, c, v) in enumerate(zip(xs, opens, closes, volumes)):
            color = C.GREEN if c >= o else C.RED
            ax_vol.bar(x_val, v, width=0.7, color=color, alpha=0.8, edgecolor=color, linewidth=0.3)
        vol_arr = np.array(volumes)
        if len(vol_arr) >= 5:
            vol_ma5 = np.convolve(vol_arr, np.ones(5)/5, mode="valid")
            ax_vol.plot(xs[4:], vol_ma5, color=C.YELLOW, linewidth=1.5, alpha=0.8, label="VOL MA5")
        ax_vol.set_ylabel("成交量", fontsize=10, color=C.TEXT_DIM, fontproperties=self._font)
        ax_vol.legend(loc="upper left", fontsize=9, facecolor=C.BG,
                      edgecolor=C.GRID, labelcolor=C.TEXT, prop=self._font)
        ax_vol.set_facecolor(C.BG)
        ax_vol.tick_params(colors=C.TEXT_DIM, labelsize=9)
        for sp in ax_vol.spines.values():
            sp.set_color(C.GRID)
        ax_vol.grid(True, color=C.GRID, alpha=0.4, linestyle=":", linewidth=0.5)
        ax_vol.set_title(f"{name} ({stock_code})  成交量分析",
                         color=C.WHITE, fontproperties=self._font, fontsize=14, pad=8, loc="left")
        plt.setp(ax_price.get_xticklabels(), visible=False)

        buf = io.BytesIO()
        fig.savefig(buf, format="rgba", dpi=dpi, facecolor=C.BG, edgecolor="none", pad_inches=0)
        plt.close(fig)
        buf.seek(0)
        return np.frombuffer(buf.getvalue(), dtype=np.uint8).reshape(h, w, 4)

    # ── 7. Fund Flow ───────────────────────────────────────────────────

    async def _render_fund_flow(
        self, stock_code: str, w: int, h: int, dpi: int,
    ) -> np.ndarray | None:
        fund = await self._fetch_fund_data(stock_code, limit=50)
        spot = await self._fetch_spot_data(stock_code)
        name = spot.get("名称", stock_code) if spot else stock_code

        w_in, h_in = w / dpi, h / dpi
        fig = plt.figure(figsize=(w_in, h_in), dpi=dpi, facecolor=C.BG)
        ax = fig.add_subplot(111, facecolor=C.BG)

        if fund:
            payload = fund[-1].get("payload", {}) if fund else {}
            labels = ["主力净流入", "超大单", "大单", "中单", "小单"]
            keys = ["主力净流入", "超大单净流入", "大单净流入", "中单净流入", "小单净流入"]
            values = []
            for k in keys:
                try:
                    values.append(float(payload.get(k, 0)) / 1e8)
                except (ValueError, TypeError):
                    values.append(0.0)

            colors = [C.GREEN if v >= 0 else C.RED for v in values]
            y_pos = range(len(labels))
            bars = ax.barh(y_pos, values, color=colors, height=0.6, alpha=0.85)
            ax.set_yticks(y_pos)
            ax.set_yticklabels(labels, fontproperties=self._font, fontsize=11, color=C.TEXT)
            for bar, val in zip(bars, values):
                label = f"{val:+.2f}亿"
                ax.text(bar.get_x() + bar.get_width() + (0.05 if val >= 0 else -0.05),
                        bar.get_y() + bar.get_height() / 2, label,
                        va="center", ha="left" if val >= 0 else "right",
                        fontsize=10, color=C.TEXT, fontproperties=self._font)

        ax.set_facecolor(C.BG)
        ax.tick_params(colors=C.TEXT_DIM, labelsize=11)
        for sp in ax.spines.values():
            sp.set_visible(False)
        ax.axvline(x=0, color=C.TEXT_DIM, linewidth=0.5, alpha=0.5)
        ax.invert_yaxis()

        title_color = C.GREEN if (fund and fund[-1].get("payload", {}).get("主力净流入", 0) >= 0) else C.RED
        ax.set_title(f"{name} ({stock_code})  资金流向", color=C.WHITE,
                     fontproperties=self._font, fontsize=16, pad=15, loc="left")

        buf = io.BytesIO()
        fig.savefig(buf, format="rgba", dpi=dpi, facecolor=C.BG, edgecolor="none", pad_inches=0)
        plt.close(fig)
        buf.seek(0)
        return np.frombuffer(buf.getvalue(), dtype=np.uint8).reshape(h, w, 4)

    # ── internal: drawing helpers ──────────────────────────────────────

    def _draw_candlesticks(
        self, ax_main, ax_vol, data: list[dict],
        price_now: float, change_pct: float,
    ) -> None:
        if not data:
            return
        payloads = [r.get("payload", {}) for r in data]
        opens = [float(p.get("开盘", p.get("open", 0))) for p in payloads]
        closes = [float(p.get("收盘", p.get("close", 0))) for p in payloads]
        highs = [float(p.get("最高", p.get("high", 0))) for p in payloads]
        lows = [float(p.get("最低", p.get("low", 0))) for p in payloads]
        volumes = [float(p.get("成交量", p.get("volume", 0))) for p in payloads]
        dates = [p.get("日期", p.get("date", str(i))) for i, p in enumerate(payloads)]
        xs = list(range(len(dates)))
        width = 0.6

        for i, (x, o, c, h_val, l_val) in enumerate(zip(xs, opens, closes, highs, lows)):
            color = C.GREEN if c >= o else C.RED
            ax_main.plot([x, x], [l_val, h_val], color=color, linewidth=0.8, solid_capstyle="round")
            body_h = abs(c - o)
            if body_h > 0:
                ax_main.add_patch(plt.Rectangle(
                    (x - width/2, min(c, o)), width, body_h,
                    facecolor=color, edgecolor=color, linewidth=0.5, alpha=0.9))
            else:
                ax_main.plot(x, c, marker="_", color=color, markersize=8)

        closes_arr = np.array(closes)
        for period, color, lw in [(5, C.MA5, 1.0), (10, C.MA10, 1.0),
                                   (20, C.MA20, 1.5), (60, C.MA60, 1.5)]:
            if len(closes_arr) >= period:
                ma = np.convolve(closes_arr, np.ones(period)/period, mode="valid")
                ax_main.plot(xs[period-1:], ma, color=color, linewidth=lw,
                             alpha=0.8, label=f"MA{period}")
        ax_main.legend(loc="upper left", fontsize=7, facecolor=C.BG + "88",
                       edgecolor=C.GRID, labelcolor=C.TEXT_DIM, prop=self._font)

        if price_now > 0:
            ax_main.axhline(y=price_now, color=C.YELLOW, linewidth=0.8, linestyle="--", alpha=0.6)
            last_x = xs[-1] if xs else 0
            ax_main.annotate(
                f"  {price_now:.2f} ({change_pct:+.2f}%)",
                xy=(last_x, price_now), fontsize=9, color=C.WHITE,
                fontproperties=self._font,
                bbox=dict(boxstyle="round,pad=0.3",
                          facecolor=C.GREEN if change_pct >= 0 else C.RED))

        for i, (x, o, c, v) in enumerate(zip(xs, opens, closes, volumes)):
            color = C.GREEN + "44" if c >= o else C.RED + "44"
            ax_vol.bar(x, v, width=width * 0.8, color=color, edgecolor=color, linewidth=0.3)

        for ax in (ax_main, ax_vol):
            ax.set_facecolor(C.BG)
            ax.tick_params(colors=C.TEXT_DIM, labelsize=8)
            for sp in ax.spines.values():
                sp.set_color(C.GRID)
            ax.grid(True, color=C.GRID, alpha=0.4, linestyle=":", linewidth=0.5)
        ax_vol.set_ylabel("VOL", fontsize=7, color=C.TEXT_DIM, fontproperties=self._font)

        if len(dates) > 20:
            step = max(1, len(dates) // 8)
            tick_xs = xs[::step]
            tick_labels = [str(d)[4:8] if len(str(d)) > 6 else str(d) for d in dates[::step]]
            ax_vol.set_xticks(tick_xs)
            ax_vol.set_xticklabels(tick_labels, fontsize=7, rotation=0)
        else:
            ax_vol.set_xticks(xs)
            ax_vol.set_xticklabels([str(d)[4:8] if len(str(d)) > 6 else str(d) for d in dates],
                                   fontsize=7, rotation=0)
        plt.setp(ax_main.get_xticklabels(), visible=False)

    def _draw_title_bar(self, ax, symbol: str, name: str,
                        price_now: float, change_pct: float) -> None:
        ax.set_facecolor(C.PANEL_BG)
        ax.set_xticks([]); ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_visible(False)
        color = C.GREEN if change_pct >= 0 else C.RED
        text = f"  {name} ({symbol})    {price_now:.2f}    {change_pct:+.2f}%"
        ax.text(0.02, 0.5, text, transform=ax.transAxes, fontsize=13,
                fontproperties=self._font, color=C.WHITE, va="center",
                bbox=dict(facecolor=color, alpha=0.2, edgecolor=color,
                          linewidth=1, boxstyle="round,pad=0.4"))

    def _draw_fund_strip(self, ax, fund_data: list[dict] | None) -> None:
        ax.set_facecolor(C.PANEL_BG)
        ax.set_xticks([]); ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_visible(False)
        if not fund_data:
            ax.text(0.5, 0.5, "等待资金流向数据...", transform=ax.transAxes,
                    ha="center", va="center", fontsize=10, fontproperties=self._font,
                    color=C.TEXT_DIM)
            return
        payload = fund_data[-1].get("payload", {}) if fund_data else {}
        items = [("主力净流入", "主力净流入"), ("超大单", "超大单净流入"), ("大单", "大单净流入")]
        x_pos = 0.05
        for label, key in items:
            try:
                val = float(payload.get(key, 0)) / 1e4
            except (ValueError, TypeError):
                val = 0.0
            color = C.GREEN if val >= 0 else C.RED
            ax.text(x_pos, 0.5, f"{label} {val:+.0f}万", transform=ax.transAxes,
                    fontsize=10, fontproperties=self._font, color=color, va="center",
                    bbox=dict(facecolor=color, alpha=0.15, edgecolor=color,
                              linewidth=0.5, boxstyle="round,pad=0.3"))
            x_pos += 0.3

    # ── internal: indicators ───────────────────────────────────────────

    @staticmethod
    def _compute_macd(closes: list[float]) -> tuple[list[float], list[float], list[float]]:
        """Compute MACD (12, 26, 9) from close prices."""
        if len(closes) < 26:
            return [], [], []
        closes_arr = np.array(closes, dtype=np.float64)

        def ema(data: np.ndarray, period: int) -> np.ndarray:
            result = np.zeros_like(data)
            result[period - 1] = data[:period].mean()
            multiplier = 2.0 / (period + 1)
            for i in range(period, len(data)):
                result[i] = (data[i] - result[i - 1]) * multiplier + result[i - 1]
            return result

        ema12 = ema(closes_arr, 12)
        ema26 = ema(closes_arr, 26)
        dif = ema12 - ema26
        dea = ema(dif, 9)
        histogram = 2.0 * (dif - dea)

        start = 33  # 26 + 9 - 1 - 1 (first valid MACD index)
        return dif[start:].tolist(), dea[start:].tolist(), histogram[start:].tolist()

    @staticmethod
    def _compute_rsi(closes: list[float], period: int = 14) -> list[float]:
        """Compute RSI indicator from close prices."""
        if len(closes) < period + 1:
            return []
        closes_arr = np.array(closes, dtype=np.float64)
        deltas = np.diff(closes_arr)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])

        rsi = [100.0 - 100.0 / (1.0 + avg_gain / max(avg_loss, 1e-10))]
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            rs = avg_gain / max(avg_loss, 1e-10)
            rsi.append(100.0 - 100.0 / (1.0 + rs))
        return rsi
