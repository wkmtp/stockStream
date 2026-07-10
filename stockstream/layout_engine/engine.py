"""Layout engine — composes the full 1920×1080 livestream frame.

Supports dynamic layout switching between presets (live, scene, classic)
at runtime without service restart.

Frame layout (live preset, default):

    ┌─────────────────────────────────────────────────────────────┐  0
    │  Title Bar: 股票名称 | 价格 | 涨跌幅 | 场景标签             │  80px
    ├──────────────┬──────────────────────────────────────────────┤
    │              │                                              │
    │  Digital     │   Chart / Scene Area                         │
    │  Human       │   width: 1440px                              │
    │  width:480px │                                              │
    │              │                                              │
    ├──────────────┴──────────────────────────────────────────────┤  960
    │  Subtitle Bar: 贵州茅台今日主力资金净流入2.1亿              │  120px
    └─────────────────────────────────────────────────────────────┘  1080

Usage::

    engine = LayoutEngine("live")
    frame_bgr = engine.compose(overlay_data)   # shape (1080, 1920, 3) BGR uint8

    # Switch layout at runtime
    engine.switch_layout("classic")
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from stockstream.layout_engine.models import (
    LayoutConfig,
    LayoutPreset,
    OverlayData,
    PRESETS,
    LivePreset,
    ScenePreset,
    ClassicPreset,
)
from stockstream.layout_engine.regions import (
    TitleBarRenderer,
    DigitalHumanRenderer,
    ChartRenderer,
    SubtitleRenderer as SubtitleBarRenderer,
    LayoutColors,
)

logger = logging.getLogger(__name__)


@dataclass
class LayoutStats:
    """Layout engine runtime statistics."""

    frames_composed: int = 0
    current_preset: str = "live"
    fps: float = 0.0
    compose_time_ms: float = 0.0
    last_compose_at: float = 0.0
    switch_count: int = 0
    errors: int = 0
    last_error: str = ""


class LayoutEngine:
    """Compose a single 1920×1080 livestream video frame from all data layers.

    Features:
      - Three named layout presets: live, scene, classic
      - Dynamic layout switching at runtime (switch_layout)
      - Per-region renderers (title bar, digital human, chart, subtitle)
      - Frame composition in BGR uint8 format
      - Statistics tracking
    """

    def __init__(
        self,
        preset: str | LayoutConfig = "live",
    ) -> None:
        self._init_from_preset(preset)
        self._stats = LayoutStats(current_preset=self._preset_name)

        # Region renderers — initialized lazily on first compose
        self._title_renderer: Optional[TitleBarRenderer] = None
        self._face_renderer: Optional[DigitalHumanRenderer] = None
        self._chart_renderer: Optional[ChartRenderer] = None
        self._subtitle_renderer: Optional[SubtitleBarRenderer] = None

    # ── preset management ──────────────────────────────────────────

    def _init_from_preset(self, preset: str | LayoutConfig) -> None:
        if isinstance(preset, LayoutConfig):
            self.cfg = preset
            # Find matching preset name
            for name, cfg in PRESETS.items():
                if cfg is preset:
                    self._preset_name = name
                    break
            else:
                self._preset_name = "custom"
        else:
            name = preset.lower()
            if name not in PRESETS:
                logger.warning("Unknown preset '%s', falling back to 'live'", preset)
                name = "live"
            self.cfg = PRESETS[name]
            self._preset_name = name

    @property
    def preset(self) -> str:
        """Current layout preset name."""
        return self._preset_name

    @property
    def available_presets(self) -> list[str]:
        """List of all available preset names."""
        return list(PRESETS.keys())

    def switch_layout(self, preset_name: str) -> bool:
        """Switch to a different layout preset at runtime.

        Args:
            preset_name: One of "live", "scene", "classic".

        Returns:
            True if switch succeeded, False if preset is unknown or unchanged.
        """
        name = preset_name.lower()
        if name not in PRESETS:
            logger.warning("Unknown preset '%s'", preset_name)
            return False
        if name == self._preset_name:
            return False

        old_name = self._preset_name
        self.cfg = PRESETS[name]
        self._preset_name = name
        self._stats.switch_count += 1
        self._stats.current_preset = name

        # Reset renderers — they depend on layout config
        self._chart_renderer = None
        self._title_renderer = None
        self._face_renderer = None
        self._subtitle_renderer = None

        logger.info("Layout switched: %s → %s", old_name, name)
        return True

    # ── lazy renderer init ─────────────────────────────────────────

    def _get_title_renderer(self) -> TitleBarRenderer:
        if self._title_renderer is None:
            self._title_renderer = TitleBarRenderer(
                font_size=28,
                bg_alpha=0.45,
            )
        return self._title_renderer

    def _get_face_renderer(self) -> DigitalHumanRenderer:
        if self._face_renderer is None:
            self._face_renderer = DigitalHumanRenderer(
                face_scale=self.cfg.face_scale,
                y_offset=self.cfg.face_y_offset,
            )
        return self._face_renderer

    def _get_chart_renderer(self) -> ChartRenderer:
        if self._chart_renderer is None:
            self._chart_renderer = ChartRenderer(config=self.cfg)
        return self._chart_renderer

    def _get_subtitle_renderer(self) -> SubtitleBarRenderer:
        if self._subtitle_renderer is None:
            self._subtitle_renderer = SubtitleBarRenderer(
                font_size=34,
                bg_alpha=0.65,
            )
        return self._subtitle_renderer

    # ── main compose ───────────────────────────────────────────────

    def compose(self, data: OverlayData) -> np.ndarray:
        """Compose a single 1920×1080 frame.

        Args:
            data: OverlayData with stock info, face frame, chart data, subtitles.

        Returns:
            BGR uint8 numpy array (1080, 1920, 3).
        """
        import cv2

        t_start = time.perf_counter()

        try:
            w, h = self.cfg.width, self.cfg.height

            # Layer 0: Background
            if data.background is not None:
                canvas = cv2.resize(data.background, (w, h))
            else:
                canvas = np.full((h, w, 3), LayoutColors.BG_DARK, dtype=np.uint8)

            # Layer 1: Title bar (top)
            self._get_title_renderer().render(
                canvas, data, self.cfg.title_bar_rect,
            )

            # Layer 2: Digital human face (left)
            self._get_face_renderer().render(
                canvas, data, self.cfg.face_rect,
            )

            # Layer 3: Chart or scene (right)
            chart = self._get_chart_renderer()
            if data.scene_rgba is not None:
                chart.render_scene(canvas, data, self.cfg.chart_rect)
            else:
                chart.render_chart(canvas, data, self.cfg.chart_rect)

            # Layer 4: Subtitle bar (bottom)
            self._get_subtitle_renderer().render(
                canvas, data, self.cfg.subtitle_rect,
            )

        except Exception as exc:
            self._stats.errors += 1
            self._stats.last_error = str(exc)
            logger.exception("LayoutEngine compose error: %s", exc)
            # Return blank frame on error
            canvas = np.full((self.cfg.height, self.cfg.width, 3),
                             LayoutColors.BG_DARK, dtype=np.uint8)

        self._stats.frames_composed += 1
        self._stats.compose_time_ms = (time.perf_counter() - t_start) * 1000.0
        self._stats.last_compose_at = time.monotonic()

        return canvas

    # ── stats ──────────────────────────────────────────────────────

    @property
    def stats(self) -> dict:
        """Return engine statistics as a dict."""
        return {
            "frames_composed": self._stats.frames_composed,
            "current_preset": self._stats.current_preset,
            "available_presets": self.available_presets,
            "compose_time_ms": round(self._stats.compose_time_ms, 2),
            "switch_count": self._stats.switch_count,
            "errors": self._stats.errors,
            "last_error": self._stats.last_error,
            "layout": {
                "width": self.cfg.width,
                "height": self.cfg.height,
                "title_bar_height": self.cfg.title_bar_height,
                "face_width": self.cfg.face_width,
                "face_x": self.cfg.face_x,
                "chart_width": self.cfg.chart_width,
                "chart_x": self.cfg.chart_x,
                "subtitle_height": self.cfg.subtitle_height,
                "main_area_height": self.cfg.main_area_height,
            },
        }

    def invalidate_chart_cache(self) -> None:
        """Force chart re-render on next compose."""
        chart = self._get_chart_renderer()
        chart.invalidate_cache()

    def reset_stats(self) -> None:
        """Reset frame counter and timing stats."""
        self._stats.frames_composed = 0
        self._stats.compose_time_ms = 0.0
        self._stats.errors = 0
        self._stats.last_error = ""


# ── factory ──────────────────────────────────────────────────────────────

def create_layout_engine(preset: str = "live") -> LayoutEngine:
    """Create a LayoutEngine with the given preset.

    Args:
        preset: One of "live", "scene", "classic". Default: "live".

    Returns:
        Configured LayoutEngine instance.
    """
    return LayoutEngine(preset=preset)
