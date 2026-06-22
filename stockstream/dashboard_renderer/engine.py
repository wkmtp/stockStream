"""Dashboard engine — 10s refresh loop, PNG cache, SceneManager integration.

Architecture:
    DashboardCollector (AkShare) → DashboardData → DashboardRenderer → DashboardResult
                                                         │
                          ┌──────────────────────────────┤
                          ▼                              ▼
                   PNG file cache                SceneManager (scene)
                   (cache/dashboard/)            (live compositor)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Optional

import numpy as np

from stockstream.dashboard_renderer.collector import DashboardCollector
from stockstream.dashboard_renderer.models import (
    DashboardConfig,
    DashboardData,
    DashboardResult,
)
from stockstream.dashboard_renderer.renderer import render_dashboard

logger = logging.getLogger(__name__)


class DashboardEngine:
    """Full-screen financial dashboard engine with 10s auto-refresh.

    Usage::

        engine = create_dashboard_engine()
        await engine.start()         # begins background 10s refresh loop
        result = engine.latest()     # get latest DashboardResult
        png_path = engine.png_path   # path to latest PNG file
        await engine.stop()          # graceful shutdown
    """

    def __init__(self, cfg: DashboardConfig | None = None) -> None:
        self.cfg = cfg or DashboardConfig()
        self._collector = DashboardCollector()
        self._latest_result: DashboardResult | None = None
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._generation_count = 0
        self._last_render_ms = 0.0
        self._last_collect_ms = 0.0
        self._error_count = 0
        self._last_error: str | None = None

        # Ensure cache directory exists
        self._cache_dir = Path(self.cfg.cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    # ── lifecycle ──────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background refresh loop."""
        if self._task and not self._task.done():
            logger.info("DashboardEngine already running, skipping start()")
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._run_forever(), name="dashboard-engine"
        )
        logger.info("DashboardEngine started (refresh=%ds)", self.cfg.refresh_seconds)

    async def stop(self) -> None:
        """Stop the background refresh loop."""
        logger.info("Stopping DashboardEngine...")
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("DashboardEngine stopped")

    # ── background loop ────────────────────────────────────────────

    async def _run_forever(self) -> None:
        """Core loop: collect → render → cache → sleep → repeat."""
        # Initial collection immediately
        await self._refresh()

        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.cfg.refresh_seconds,
                )
                break  # stop_event was set
            except asyncio.TimeoutError:
                await self._refresh()

    async def _refresh(self) -> None:
        """One cycle: collect data → render dashboard → update cache."""
        t_start = time.perf_counter()

        # ── Collect ──
        try:
            data = await self._collector.collect_all()
            self._last_collect_ms = (time.perf_counter() - t_start) * 1000.0
        except Exception as exc:
            self._error_count += 1
            self._last_error = str(exc)
            logger.warning("Dashboard collect failed: %s", exc)
            return

        if not data.has_data:
            logger.debug("Dashboard: no index data available, skipping render")
            return

        # ── Render ──
        try:
            result = render_dashboard(data, self.cfg)
            self._last_render_ms = result.render_time_ms
        except Exception as exc:
            self._error_count += 1
            self._last_error = f"render: {exc}"
            logger.warning("Dashboard render failed: %s", exc)
            return

        # ── Cache ──
        self._latest_result = result
        self._generation_count += 1
        self._last_error = None

        # Save PNG to disk
        try:
            png_path = self._cache_dir / "dashboard_latest.png"
            with open(png_path, "wb") as f:
                f.write(result.png_bytes)
            logger.debug("Dashboard rendered (%.0fms, size=%dKB) → %s",
                         result.render_time_ms, len(result.png_bytes) // 1024, png_path)
        except OSError as exc:
            logger.warning("Failed to write dashboard PNG: %s", exc)

    # ── public API ─────────────────────────────────────────────────

    async def refresh_now(self) -> DashboardResult | None:
        """Force an immediate refresh, return the result."""
        await self._refresh()
        return self._latest_result

    def latest(self) -> DashboardResult | None:
        """Get the latest cached DashboardResult (non-blocking)."""
        return self._latest_result

    @property
    def png_path(self) -> str:
        """Path to the latest PNG file on disk."""
        return str(self._cache_dir / "dashboard_latest.png")

    @property
    def png_bytes(self) -> bytes:
        """Latest PNG bytes, or empty if not yet rendered."""
        if self._latest_result:
            return self._latest_result.png_bytes
        return b""

    @property
    def rgba(self) -> np.ndarray | None:
        """Latest RGBA numpy array, or None."""
        if self._latest_result:
            return self._latest_result.rgba
        return None

    @property
    def data(self) -> DashboardData | None:
        """Latest DashboardData snapshot."""
        if self._latest_result:
            return self._latest_result.data
        return None

    @property
    def stats(self) -> dict:
        """Engine statistics for monitoring."""
        return {
            "running": self._task is not None and not self._task.done(),
            "generation_count": self._generation_count,
            "last_render_ms": round(self._last_render_ms, 2),
            "last_collect_ms": round(self._last_collect_ms, 2),
            "error_count": self._error_count,
            "last_error": self._last_error,
            "refresh_seconds": self.cfg.refresh_seconds,
            "has_data": self._latest_result is not None,
            "png_path": self.png_path,
        }


# ── factory ────────────────────────────────────────────────────────────────

def create_dashboard_engine(
    refresh_seconds: int = 10,
    cache_dir: str = "cache/dashboard",
    width: int = 1920,
    height: int = 1080,
) -> DashboardEngine:
    """Create a DashboardEngine with the given config."""
    cfg = DashboardConfig(
        width=width,
        height=height,
        refresh_seconds=refresh_seconds,
        cache_dir=cache_dir,
    )
    return DashboardEngine(cfg)
