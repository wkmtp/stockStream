"""Heatmap Engine — async sector data collection + chart rendering + PNG caching.

Core engine that ties together the SectorCollector and renderers.
Runs a background refresh loop every 30 seconds, caches rendered PNGs
to cache/heatmap/, and exposes a clean async API for chart retrieval.

Architecture:
    ┌─────────────────┐     ┌──────────────────┐     ┌───────────────────┐
    │  SectorCollector │────▶│  SectorSnapshot   │────▶│  renderer.py      │
    │  (AkShare)       │     │  (ranked sectors) │     │  (matplotlib)     │
    └────────┬─────────┘     └────────┬──────────┘     └────────┬──────────┘
             │                        │                         │
             ▼                        ▼                         ▼
    ┌──────────────────────────────────────────────────────────────────┐
    │                     HeatmapEngine                                 │
    │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
    │  │  refresh loop │  │  PNG cache   │  │  get_heatmap() API   │   │
    │  │  (30s)        │  │  (file-based)│  │  (async, cached)    │   │
    │  └──────────────┘  └──────────────┘  └──────────────────────┘   │
    └──────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── sibling imports ───────────────────────────────────────────────────────

from stockstream.heatmap_engine.collector import SectorCollector
from stockstream.heatmap_engine.models import HeatmapType, SectorSnapshot
from stockstream.heatmap_engine.renderer import render_heatmap, render_all
from stockstream.video.scene_manager import SceneManager, SceneType


class HeatmapEngine:
    """Async heatmap engine with 30-second refresh and PNG file caching.

    Usage::

        engine = HeatmapEngine(
            cache_dir="cache/heatmap",
            refresh_seconds=30,
            scene_manager=scene_manager,
        )
        await engine.start()              # begin background refresh loop
        result = await engine.get_heatmap(HeatmapType.TOP20_GAINERS)
        # result.file_path → "cache/heatmap/top20_gainers.png"
    """

    def __init__(
        self,
        cache_dir: str = "cache/heatmap",
        refresh_seconds: int = 30,
        scene_manager: SceneManager | None = None,
        default_width: int = 1440,
        default_height: int = 880,
        default_dpi: int = 100,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.refresh_seconds = refresh_seconds
        self.scene_manager = scene_manager
        self.default_width = default_width
        self.default_height = default_height
        self.default_dpi = default_dpi

        # ── internal state ──────────────────────────────────────────
        self._collector = SectorCollector()
        self._snapshot: SectorSnapshot | None = None
        self._lock = asyncio.Lock()
        self._last_render: dict[str, float] = {}
        self._last_collect_time: float = 0.0
        self._refresh_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._running = False

        # Stats
        self._collect_count: int = 0
        self._render_count: int = 0
        self._last_error: str | None = None

        # Ensure cache directory
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ── lifecycle ────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background refresh loop.

        Idempotent — calling start() on an already-running engine is a no-op.
        """
        if self._running:
            logger.info("HeatmapEngine already running, skipping start()")
            return

        self._stop_event.clear()
        self._running = True
        self._refresh_task = asyncio.create_task(
            self._refresh_loop(), name="heatmap-engine-refresh"
        )
        logger.info(
            "HeatmapEngine started (refresh=%ds, cache_dir=%s)",
            self.refresh_seconds, str(self.cache_dir.resolve()),
        )

    async def stop(self) -> None:
        """Signal the background loop to stop and wait for it."""
        logger.info("Stopping HeatmapEngine...")
        self._stop_event.set()
        self._running = False
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
        logger.info("HeatmapEngine stopped (collects=%d, renders=%d)",
                     self._collect_count, self._render_count)

    # ── public API ───────────────────────────────────────────────────

    @property
    def snapshot(self) -> SectorSnapshot | None:
        """Return the latest sector snapshot (may be None before first collect)."""
        return self._snapshot

    @property
    def is_running(self) -> bool:
        return self._running

    async def get_snapshot(self, force_refresh: bool = False) -> SectorSnapshot | None:
        """Get the latest sector snapshot.

        Args:
            force_refresh: If True, collect fresh data immediately.
        """
        if force_refresh or self._snapshot is None:
            await self._collect_once()
        return self._snapshot

    async def get_heatmap(
        self,
        chart_type: HeatmapType,
        *,
        width_px: int | None = None,
        height_px: int | None = None,
        dpi: int | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Return the latest heatmap/chart for a given chart type.

        If the cached PNG is younger than *refresh_seconds*, returns it
        directly.  Otherwise re-renders from the latest sector snapshot.

        Args:
            chart_type: Which heatmap chart to generate.
            width_px, height_px, dpi: Override default dimensions.
            force_refresh: Bypass cache and force re-render.

        Returns:
            dict with keys: file_path, chart_type, chart_label, success, error,
            width_px, height_px, rendered_at, snapshot_time, sector_count.
        """
        w = width_px or self.default_width
        h = height_px or self.default_height
        d = dpi or self.default_dpi
        cache_key = f"heatmap_{chart_type.value}"

        # Fast path: cache hit
        if not force_refresh and self._is_cache_fresh(cache_key):
            png_path = self._png_path(chart_type)
            if png_path.exists():
                return self._make_result(chart_type, str(png_path.resolve()), w, h)

        # Render under lock
        async with self._lock:
            if not force_refresh and self._is_cache_fresh(cache_key):
                png_path = self._png_path(chart_type)
                if png_path.exists():
                    return self._make_result(chart_type, str(png_path.resolve()), w, h)

            return await self._render_and_cache(chart_type, w, h, d, cache_key)

    async def get_heatmap_png_bytes(
        self,
        chart_type: HeatmapType,
        *,
        width_px: int | None = None,
        height_px: int | None = None,
        force_refresh: bool = False,
    ) -> bytes | None:
        """Convenience: return raw PNG bytes instead of a file path."""
        result = await self.get_heatmap(
            chart_type,
            width_px=width_px, height_px=height_px,
            force_refresh=force_refresh,
        )
        if result["success"]:
            return Path(result["file_path"]).read_bytes()
        return None

    async def refresh_all(self) -> dict[str, dict[str, Any]]:
        """Force-refresh all heatmap chart types and return results."""
        results: dict[str, dict[str, Any]] = {}
        for ct in HeatmapType:
            if ct == HeatmapType.COMPOSITE_DASHBOARD:
                continue
            result = await self.get_heatmap(ct, force_refresh=True)
            results[ct.value] = result
        return results

    async def collect_now(self) -> SectorSnapshot | None:
        """Manually trigger a sector data collection (does not wait for loop)."""
        return await self._collect_once()

    async def list_cache(self) -> list[dict[str, Any]]:
        """List all cached heatmap PNG files with metadata."""
        entries = []
        for p in sorted(self.cache_dir.glob("*.png")):
            stat = p.stat()
            entries.append({
                "file": p.name,
                "size_bytes": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            })
        return entries

    async def clear_cache(self) -> int:
        """Delete all cached heatmap PNGs."""
        deleted = 0
        for p in self.cache_dir.glob("*.png"):
            p.unlink()
            deleted += 1
        self._last_render.clear()
        logger.info("Cleared %d cached heatmap(s)", deleted)
        return deleted

    def get_stats(self) -> dict[str, Any]:
        """Return engine statistics."""
        return {
            "running": self._running,
            "refresh_seconds": self.refresh_seconds,
            "cache_dir": str(self.cache_dir.resolve()),
            "collect_count": self._collect_count,
            "render_count": self._render_count,
            "last_collect_time": datetime.fromtimestamp(
                self._last_collect_time, tz=timezone.utc
            ).isoformat() if self._last_collect_time else None,
            "last_error": self._last_error,
            "sector_count": len(self._snapshot.sectors) if self._snapshot else 0,
            "snapshot_time": self._snapshot.collected_at.isoformat() if self._snapshot else None,
            "up_sectors": self._snapshot.up_sectors if self._snapshot else 0,
            "down_sectors": self._snapshot.down_sectors if self._snapshot else 0,
            "cached_files": sum(1 for _ in self.cache_dir.glob("*.png")),
        }

    # ── background refresh loop ──────────────────────────────────────

    async def _refresh_loop(self) -> None:
        """Core loop: collect → render → sleep → repeat."""
        while not self._stop_event.is_set():
            try:
                await self._collect_once()
                if self._snapshot and self._snapshot.sectors:
                    # Render all chart types after successful collection
                    await self._render_all_types()
                    # Push sector data to scene_manager
                    self._push_to_scene_manager()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                self._last_error = str(exc)
                logger.warning("HeatmapEngine refresh cycle failed: %s", exc)

            # Sleep until next cycle
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.refresh_seconds,
                )
                return  # stop_event was set
            except asyncio.TimeoutError:
                pass  # normal: continue loop

    async def _collect_once(self) -> SectorSnapshot | None:
        """Run one collection cycle."""
        start = time.monotonic()
        try:
            snapshot = await self._collector.collect()
            self._snapshot = snapshot
            self._collect_count += 1
            self._last_collect_time = time.monotonic()
            self._last_error = None
            elapsed = (time.monotonic() - start) * 1000
            logger.debug(
                "Sector collection: %d sectors in %.0f ms (up=%d down=%d)",
                snapshot.count, elapsed, snapshot.up_sectors, snapshot.down_sectors,
            )
            return snapshot
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("Sector collection failed: %s", exc)
            return None

    async def _render_all_types(self) -> None:
        """Re-render all heatmap chart types and cache to disk."""
        if self._snapshot is None or not self._snapshot.sectors:
            return

        w, h, d = self.default_width, self.default_height, self.default_dpi
        for ct in HeatmapType:
            if ct == HeatmapType.COMPOSITE_DASHBOARD:
                continue  # dashboard is heavy, render on demand
            try:
                rgba = render_heatmap(self._snapshot, ct, w, h, d)
                if rgba is not None:
                    self._save_png(ct, rgba)
                    self._render_count += 1
            except Exception as exc:
                logger.warning("Auto-render failed for %s: %s", ct.value, exc)

    def _push_to_scene_manager(self) -> None:
        """Push latest sector data to the SceneManager for live scene rendering."""
        if self.scene_manager is None or self._snapshot is None:
            return
        try:
            sector_data = self._snapshot.to_scene_data()
            self.scene_manager.update_market_data(sector_data=sector_data)
        except Exception as exc:
            logger.debug("Failed to push sector data to scene_manager: %s", exc)

    # ── internal: cache logic ────────────────────────────────────────

    def _png_path(self, chart_type: HeatmapType) -> Path:
        return self.cache_dir / f"{chart_type.value}.png"

    def _is_cache_fresh(self, cache_key: str) -> bool:
        last = self._last_render.get(cache_key, 0)
        return (time.monotonic() - last) < self.refresh_seconds

    async def _render_and_cache(
        self,
        chart_type: HeatmapType,
        w: int, h: int, dpi: int,
        cache_key: str,
    ) -> dict[str, Any]:
        """Collect data → render → save PNG → return result."""
        start = time.monotonic()

        # Ensure we have data
        if self._snapshot is None:
            await self._collect_once()

        if self._snapshot is None or not self._snapshot.sectors:
            return self._make_result(
                chart_type, "", w, h,
                error="No sector data available",
            )

        try:
            rgba = render_heatmap(self._snapshot, chart_type, w, h, dpi)
        except Exception as exc:
            logger.exception("Heatmap render failed %s: %s", chart_type.value, exc)
            return self._make_result(chart_type, "", w, h, error=str(exc))

        if rgba is None:
            return self._make_result(chart_type, "", w, h, error="Render returned None")

        png_path = self._save_png(chart_type, rgba)
        self._last_render[cache_key] = time.monotonic()
        self._render_count += 1

        elapsed = (time.monotonic() - start) * 1000
        logger.debug("Rendered %s → %s (%.0f ms)", chart_type.value, png_path.name, elapsed)

        return self._make_result(chart_type, str(png_path.resolve()), w, h)

    def _save_png(self, chart_type: HeatmapType, rgba: np.ndarray) -> Path:
        """Save an RGBA numpy array as PNG, atomic write."""
        from PIL import Image
        img = Image.fromarray(rgba, mode="RGBA")
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        png_bytes = buf.getvalue()

        png_path = self._png_path(chart_type)
        tmp_path = png_path.with_suffix(".tmp")
        tmp_path.write_bytes(png_bytes)
        tmp_path.replace(png_path)
        return png_path

    def _make_result(
        self,
        chart_type: HeatmapType,
        file_path: str,
        width_px: int,
        height_px: int,
        error: str | None = None,
    ) -> dict[str, Any]:
        return {
            "chart_type": chart_type.value,
            "chart_label": chart_type.label,
            "file_path": file_path,
            "success": error is None,
            "error": error,
            "width_px": width_px,
            "height_px": height_px,
            "rendered_at": datetime.now(timezone.utc).isoformat(),
            "snapshot_time": self._snapshot.collected_at.isoformat() if self._snapshot else None,
            "sector_count": len(self._snapshot.sectors) if self._snapshot else 0,
        }


# ── factory ───────────────────────────────────────────────────────────────


def create_heatmap_engine(
    scene_manager: SceneManager | None = None,
    cache_dir: str = "cache/heatmap",
    refresh_seconds: int = 30,
) -> HeatmapEngine:
    """Create a HeatmapEngine with default settings."""
    return HeatmapEngine(
        cache_dir=cache_dir,
        refresh_seconds=refresh_seconds,
        scene_manager=scene_manager,
    )
