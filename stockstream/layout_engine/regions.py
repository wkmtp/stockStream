"""Layout region renderers — each draws one rectangular area of the frame.

Regions:
  - TitleBarRenderer   : top bar with stock info, price, change%
  - DigitalHumanRenderer : face frame on the left
  - ChartRenderer      : K-line chart or scene content on the right
  - SubtitleRenderer   : bottom subtitle bar
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from stockstream.layout_engine.models import LayoutConfig, OverlayData, RegionRect

logger = logging.getLogger(__name__)

# Lazy imports for heavy dependencies
_SUBTITLE_RENDERER = None
_CHART_RENDERER = None


def _get_subtitle_renderer() -> object:
    global _SUBTITLE_RENDERER
    if _SUBTITLE_RENDERER is None:
        from stockstream.video.subtitle_renderer import SubtitleRenderer
        _SUBTITLE_RENDERER = SubtitleRenderer
    return _SUBTITLE_RENDERER


def _get_chart_renderer() -> object:
    global _CHART_RENDERER
    if _CHART_RENDERER is None:
        from stockstream.video.chart_renderer import StockChartRenderer, ChartColors
        _CHART_RENDERER = (StockChartRenderer, ChartColors)
    return _CHART_RENDERER


# ── colour palette ───────────────────────────────────────────────────────

class LayoutColors:
    BG_DARK = (13, 17, 23)        # main background
    BG_PANEL = (22, 27, 34)       # panel background
    BG_FACE = (16, 20, 27)        # face area background
    BORDER = (48, 54, 61)         # separator lines
    GREEN = (63, 185, 80)         # up colour
    RED = (248, 81, 73)           # down colour
    TEXT_WHITE = (201, 209, 217)  # text
    TEXT_DIM = (139, 148, 158)    # dim text
    OVERLAY_BG = (22, 27, 34)     # semi-transparent overlay bg


# ── utility ──────────────────────────────────────────────────────────────

def _overlay_rgba(
    canvas: np.ndarray,
    rgba: np.ndarray,
    x: int, y: int, w: int, h: int,
) -> None:
    """Blend an RGBA image onto a BGR canvas at the given position."""
    import cv2

    target_h = min(h, canvas.shape[0] - y)
    target_w = min(w, canvas.shape[1] - x)
    if target_h <= 0 or target_w <= 0:
        return

    rgba_resized = cv2.resize(rgba, (target_w, target_h))
    overlay_bgr = cv2.cvtColor(rgba_resized[:, :, :3], cv2.COLOR_RGB2BGR)
    alpha = (rgba_resized[:, :, 3].astype(np.float32) / 255.0)
    alpha_3ch = np.expand_dims(alpha, axis=-1)

    roi = canvas[y:y + target_h, x:x + target_w]
    blended = (overlay_bgr * alpha_3ch + roi * (1.0 - alpha_3ch)).astype(np.uint8)
    canvas[y:y + target_h, x:x + target_w] = blended


def _darken_region(
    canvas: np.ndarray,
    rect: RegionRect,
    color: tuple[int, int, int] = LayoutColors.BG_PANEL,
    alpha: float = 0.5,
) -> None:
    """Apply a semi-transparent coloured rectangle over a region."""
    import cv2

    overlay = canvas.copy()
    cv2.rectangle(overlay, (rect.x, rect.y), (rect.x2, rect.y2), color, -1)
    canvas[:] = cv2.addWeighted(canvas, 1.0 - alpha, overlay, alpha, 0)


def _draw_separator(
    canvas: np.ndarray,
    x1: int, y1: int, x2: int, y2: int,
    color: tuple[int, int, int] = LayoutColors.BORDER,
    thickness: int = 2,
) -> None:
    """Draw a vertical or horizontal separator line."""
    import cv2
    cv2.line(canvas, (x1, y1), (x2, y2), color, thickness)


# ── Title bar renderer ───────────────────────────────────────────────────

class TitleBarRenderer:
    """Render the top title bar: stock name, price, change%, optional extra label.

    Uses PIL for anti-aliased text rendering.
    """

    def __init__(
        self,
        font_size: int = 28,
        bg_alpha: float = 0.45,
    ) -> None:
        self.font_size = font_size
        self.bg_alpha = bg_alpha
        self._renderer = None

    def _get_renderer(self):
        if self._renderer is None:
            SR = _get_subtitle_renderer()
            self._renderer = SR(
                font_size=self.font_size,
                bg_alpha=self.bg_alpha,
                padding=6,
            )
            self._small_renderer = SR(font_size=20, bg_alpha=0.35, padding=4)
        return self._renderer

    def render(
        self,
        canvas: np.ndarray,
        data: OverlayData,
        rect: RegionRect,
    ) -> None:
        """Draw the title bar onto the canvas."""
        import cv2

        # Dark panel background
        _darken_region(canvas, rect, LayoutColors.OVERLAY_BG, 0.5)
        _draw_separator(canvas, rect.x, rect.y2 - 1, rect.x2, rect.y2 - 1,
                        LayoutColors.BORDER, 2)

        # Build info text
        color = LayoutColors.GREEN if data.change_pct >= 0 else LayoutColors.RED
        up_down = "+" if data.change_pct >= 0 else ""

        parts = []
        if data.name:
            parts.append(f"{data.name}")
            if data.symbol:
                parts.append(f"({data.symbol})")
        else:
            parts.append("StockStream AI 直播")
        parts.append("  |  ")
        parts.append(f"{data.price_now:.2f}")
        parts.append(f"  {up_down}{data.change_pct:.2f}%")

        if data.title_extra:
            parts.append(f"  |  {data.title_extra}")

        info_text = "".join(parts)

        # Render via subtitle renderer
        renderer = self._get_renderer()
        text_rgba = renderer.render(
            info_text,
            width=rect.width - 20,
            height=rect.height,
            align="left",
            speaker_label="",
        )
        _overlay_rgba(canvas, text_rgba, 10, rect.y, rect.width - 20, rect.height)


# ── Digital human (face) renderer ─────────────────────────────────────────

class DigitalHumanRenderer:
    """Render the digital human face on the left side of the frame."""

    def __init__(self, face_scale: float = 0.78, y_offset: int = 20) -> None:
        self.face_scale = face_scale
        self.y_offset = y_offset

    def render(
        self,
        canvas: np.ndarray,
        data: OverlayData,
        rect: RegionRect,
    ) -> None:
        """Place the digital human face into the left region."""
        import cv2

        # Background panel
        _darken_region(canvas, rect, LayoutColors.BG_FACE, 0.55)

        # Separator on the right edge
        _draw_separator(canvas, rect.x2 - 1, rect.y, rect.x2 - 1, rect.y2,
                        LayoutColors.BORDER, 2)

        # Scene label at top of face area (scene mode)
        if data.scene_label:
            SR = _get_subtitle_renderer()
            small = SR(font_size=18, bg_alpha=0.3, padding=4)
            label_rgba = small.render(
                data.scene_label,
                width=rect.width - 10,
                height=30,
                align="center",
                speaker_label="",
            )
            _overlay_rgba(canvas, label_rgba, 5, rect.y + 5,
                          rect.width - 10, 30)

        # Face frame
        if data.face_frame is not None:
            face_img = data.face_frame
            target_w = int(rect.width * self.face_scale)
            target_h = int(rect.height * self.face_scale)

            aspect = face_img.shape[1] / max(face_img.shape[0], 1)
            if target_w / target_h > aspect:
                target_w = int(target_h * aspect)
            else:
                target_h = int(target_w / aspect)

            face_resized = cv2.resize(face_img, (target_w, target_h))

            fx = rect.x + (rect.width - target_w) // 2
            fy = rect.y + self.y_offset + (rect.height - self.y_offset - target_h) // 2

            fw_clamp = min(target_w, rect.x2 - fx)
            fh_clamp = min(target_h, rect.y2 - fy)

            if fw_clamp > 0 and fh_clamp > 0:
                canvas[fy:fy + fh_clamp, fx:fx + fw_clamp] = \
                    face_resized[:fh_clamp, :fw_clamp]


# ── Chart area renderer ──────────────────────────────────────────────────

class ChartRenderer:
    """Render the K-line chart or scene content on the right side."""

    def __init__(self, config: LayoutConfig) -> None:
        self.cfg = config
        self._chart_renderer = None
        self._cached_rgba: Optional[np.ndarray] = None
        self._last_render_time: float = 0.0
        self._cache_ttl: float = 3.0  # seconds

    def _get_chart(self):
        if self._chart_renderer is None:
            StockChartRenderer, _ = _get_chart_renderer()
            chart_w = self.cfg.chart_width
            chart_h = self.cfg.main_area_height
            self._chart_renderer = StockChartRenderer(
                figsize=(chart_w / self.cfg.chart_dpi, chart_h / self.cfg.chart_dpi),
                dpi=self.cfg.chart_dpi,
            )
        return self._chart_renderer

    def render_chart(
        self,
        canvas: np.ndarray,
        data: OverlayData,
        rect: RegionRect,
    ) -> None:
        """Render K-line chart into the right region."""
        import cv2
        import time

        # Background
        _darken_region(canvas, rect, LayoutColors.BG_DARK, 0.4)

        if not data.kline_data:
            # No data — show placeholder text
            SR = _get_subtitle_renderer()
            placeholder = SR(font_size=32, bg_alpha=0.0, padding=0)
            txt_rgba = placeholder.render(
                "等待行情数据...",
                width=rect.width,
                height=rect.height,
                align="center",
                speaker_label="",
            )
            _overlay_rgba(canvas, txt_rgba, rect.x, rect.y, rect.width, rect.height)
            return

        # Render chart
        now = time.monotonic()
        if self._cached_rgba is None or (now - self._last_render_time) > self._cache_ttl:
            chart = self._get_chart()
            self._cached_rgba = chart.render_kline(
                symbol=data.symbol,
                name=data.name,
                kline_data=data.kline_data,
                fund_data=data.fund_data,
                price_now=data.price_now,
                change_pct=data.change_pct,
            )
            self._last_render_time = now

        chart_rgba = self._cached_rgba
        if chart_rgba is None:
            return

        ch, cw = chart_rgba.shape[:2]
        scale = min(rect.width / cw, rect.height / ch)
        new_w = int(cw * scale)
        new_h = int(ch * scale)

        chart_bgr = cv2.cvtColor(chart_rgba[:, :, :3], cv2.COLOR_RGB2BGR)
        chart_bgr = cv2.resize(chart_bgr, (new_w, new_h))

        if chart_rgba.shape[2] >= 4:
            alpha = chart_rgba[:, :, 3:4].astype(np.float32) / 255.0
            alpha = cv2.resize(alpha, (new_w, new_h))
            if alpha.ndim == 2:
                alpha = np.expand_dims(alpha, axis=-1)
        else:
            alpha = np.ones((new_h, new_w, 1), dtype=np.float32)

        # Center in chart region
        offset_x = (rect.width - new_w) // 2
        offset_y = (rect.height - new_h) // 2
        px = rect.x + offset_x
        py = rect.y + offset_y
        pw = min(new_w, canvas.shape[1] - px)
        ph = min(new_h, canvas.shape[0] - py)

        if pw > 0 and ph > 0:
            roi = canvas[py:py + ph, px:px + pw]
            blended = (chart_bgr[:ph, :pw] * alpha[:ph, :pw] +
                       roi * (1.0 - alpha[:ph, :pw])).astype(np.uint8)
            canvas[py:py + ph, px:px + pw] = blended

    def render_scene(
        self,
        canvas: np.ndarray,
        data: OverlayData,
        rect: RegionRect,
    ) -> None:
        """Render pre-rendered scene content (from SceneManager) into the right region."""
        import cv2

        _darken_region(canvas, rect, LayoutColors.BG_DARK, 0.4)

        if data.scene_rgba is None:
            return

        scene_rgba = data.scene_rgba
        sh_rgba, sw_rgba = scene_rgba.shape[:2]

        scale = min(rect.width / sw_rgba, rect.height / sh_rgba)
        new_w = int(sw_rgba * scale)
        new_h = int(sh_rgba * scale)

        scene_bgr = cv2.cvtColor(scene_rgba[:, :, :3], cv2.COLOR_RGB2BGR)
        scene_bgr = cv2.resize(scene_bgr, (new_w, new_h))

        if scene_rgba.shape[2] >= 4:
            alpha = scene_rgba[:, :, 3:4].astype(np.float32) / 255.0
            alpha = cv2.resize(alpha, (new_w, new_h))
            if alpha.ndim == 2:
                alpha = np.expand_dims(alpha, axis=-1)
        else:
            alpha = np.ones((new_h, new_w, 1), dtype=np.float32)

        offset_x = (rect.width - new_w) // 2
        offset_y = (rect.height - new_h) // 2
        px = rect.x + offset_x
        py = rect.y + offset_y
        pw = min(new_w, canvas.shape[1] - px)
        ph = min(new_h, canvas.shape[0] - py)

        if pw > 0 and ph > 0:
            roi = canvas[py:py + ph, px:px + pw]
            blended = (scene_bgr[:ph, :pw] * alpha[:ph, :pw] +
                       roi * (1.0 - alpha[:ph, :pw])).astype(np.uint8)
            canvas[py:py + ph, px:px + pw] = blended

    def invalidate_cache(self) -> None:
        """Force re-render on next compose."""
        self._cached_rgba = None


# ── Subtitle bar renderer ────────────────────────────────────────────────

class SubtitleRenderer:
    """Render the bottom subtitle bar."""

    def __init__(
        self,
        font_size: int = 34,
        bg_alpha: float = 0.65,
    ) -> None:
        self.font_size = font_size
        self.bg_alpha = bg_alpha
        self._renderer = None
        self._bottom_renderer = None

    def _get_renderer(self):
        if self._renderer is None:
            SR = _get_subtitle_renderer()
            self._renderer = SR(font_size=self.font_size, bg_alpha=self.bg_alpha)
        return self._renderer

    def _get_bottom_renderer(self):
        if self._bottom_renderer is None:
            SR = _get_subtitle_renderer()
            self._bottom_renderer = SR(font_size=18, bg_alpha=0.4, padding=6)
        return self._bottom_renderer

    def render(
        self,
        canvas: np.ndarray,
        data: OverlayData,
        rect: RegionRect,
    ) -> None:
        """Draw subtitle bar at the bottom."""
        import cv2

        # Background panel
        _darken_region(canvas, rect, LayoutColors.BG_PANEL, 0.5)
        _draw_separator(canvas, rect.x, rect.y, rect.x2, rect.y,
                        LayoutColors.BORDER, 1)

        # Subtitle text
        if data.subtitle_visible and data.subtitle_text:
            renderer = self._get_renderer()
            sub_rgba = renderer.render(
                data.subtitle_text,
                width=rect.width,
                height=rect.height,
                speaker_label=data.speaker_label,
            )
            _overlay_rgba(canvas, sub_rgba, rect.x, rect.y, rect.width, rect.height)

    def render_bottom_bar(
        self,
        canvas: np.ndarray,
        rect: RegionRect,
    ) -> None:
        """Draw a compact disclaimer bar (used in classic mode below subtitle)."""
        import cv2

        _darken_region(canvas, rect, LayoutColors.BG_DARK, 0.45)
        _draw_separator(canvas, rect.x, rect.y, rect.x2, rect.y,
                        LayoutColors.BORDER, 1)

        bottom_text = (
            "© StockStream AI 直播  |  "
            "内容仅供参考，不构成投资建议  |  "
            "投资有风险，入市需谨慎"
        )
        renderer = self._get_bottom_renderer()
        text_rgba = renderer.render_simple(
            bottom_text,
            width=rect.width - 20,
            height=rect.height,
        )
        _overlay_rgba(canvas, text_rgba, 10, rect.y, rect.width - 20, rect.height)
