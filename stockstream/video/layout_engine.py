"""Layout engine — composes the full digital human livestream frame.

Two layout modes supported:

1. **Classic mode** (chart 62% left / face 38% right):
   background → chart → face (digital human) → data panel → subtitle → bottom bar

2. **Scene mode** (face 25% left / scene 75% right):
   background → scene content → face → data panel → subtitle → bottom bar
   Scene content is dynamically selected by SmartSceneEngine.

Frame layout (1920×1080):

Classic:
┌─────────────────────────────────────────────────────┐
│  Stock Info Bar: 股票名称 | 价格 | 涨跌幅 | 状态 ... │  60px
├───────────────────────────────┬─────────────────────┤
│                               │                     │
│   K-line / Price Chart        │   Digital Human     │
│   (main chart area)           │   (face overlay)    │  760px
│                               │                     │
├───────────────────────────────┴─────────────────────┤
│  Fund Flow / Data Panel Strip                       │  120px
├─────────────────────────────────────────────────────┤
│  ▎  Subtitle / Caption Bar                          │  80px
├─────────────────────────────────────────────────────┤
│  Bottom Bar: © StockStream AI | ...                  │  40px
└─────────────────────────────────────────────────────┘

Scene mode:
┌─────────────────────────────────────────────────────┐
│  Stock Info Bar: 股票名称 | 价格 | 涨跌幅 | 场景名称  │  60px
├──────────┬──────────────────────────────────────────┤
│          │                                          │
│ Digital  │   Dynamic Scene Content                  │
│  Human   │   (K线/MACD/RSI/板块热力图/...)           │  880px
│  (25%)   │   (75% right)                            │
│          │                                          │
├──────────┴──────────────────────────────────────────┤
│  ▎  Subtitle / Caption Bar                          │  80px
├─────────────────────────────────────────────────────┤
│  Bottom Bar: © StockStream AI | ...                  │  40px
└─────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from stockstream.video.chart_renderer import StockChartRenderer, ChartColors
from stockstream.video.subtitle_renderer import SubtitleRenderer

logger = logging.getLogger(__name__)


# ── config ──────────────────────────────────────────────────────────────

@dataclass
class LayoutConfig:
    """Video frame layout geometry and styling.

    Two layout modes via ``scene_mode``:
        - False (classic): chart 62% left / face 38% right + data panel strip
        - True (scene):    face 25% left / scene 75% right, no data panel strip
    """

    # Frame dimensions
    width: int = 1920
    height: int = 1080

    # Top info bar
    top_bar_height: int = 60

    # Main content area split (classic mode)
    chart_width_ratio: float = 0.62   # chart takes 62%, face takes 38%
    main_area_height: int = 760

    # Scene mode layout
    scene_mode: bool = False           # True = face-left-25% + scene-right-75%
    face_width_ratio: float = 0.25     # face takes 25% in scene mode
    scene_main_area_height: int = 880  # main area in scene mode (no data panel)

    # Data panel strip (classic mode only)
    data_panel_height: int = 120

    # Subtitle bar
    subtitle_height: int = 80

    # Bottom bar
    bottom_bar_height: int = 40

    # Face size and position (inside the face area)
    face_scale: float = 0.75          # % of face area width
    face_y_offset: int = 20           # px from top of face area

    # Chart renderer DPI
    chart_dpi: int = 100

    @property
    def chart_area_width(self) -> int:
        if self.scene_mode:
            return int(self.width * (1.0 - self.face_width_ratio))
        return int(self.width * self.chart_width_ratio)

    @property
    def face_area_width(self) -> int:
        if self.scene_mode:
            return int(self.width * self.face_width_ratio)
        return self.width - self.chart_area_width

    @property
    def face_area_x(self) -> int:
        if self.scene_mode:
            return 0  # face on the left
        return self.chart_area_width  # face on the right

    @property
    def scene_area_x(self) -> int:
        """X offset of the scene content area (scene mode)."""
        return self.face_area_width

    @property
    def main_y_start(self) -> int:
        return self.top_bar_height

    @property
    def effective_main_height(self) -> int:
        """Height of the main content area in current mode."""
        if self.scene_mode:
            return self.scene_main_area_height
        return self.main_area_height

    @property
    def data_panel_y(self) -> int:
        if self.scene_mode:
            return self.top_bar_height + self.scene_main_area_height
        return self.top_bar_height + self.main_area_height

    @property
    def subtitle_y(self) -> int:
        return self.data_panel_y + self.data_panel_height

    @property
    def bottom_bar_y(self) -> int:
        return self.subtitle_y + self.subtitle_height


@dataclass
class OverlayData:
    """Dynamic data for one frame of the livestream."""

    # Stock info
    symbol: str = ""
    name: str = ""
    price_now: float = 0.0
    change_pct: float = 0.0

    # Chart data
    kline_data: list[dict] = field(default_factory=list)
    fund_data: list[dict] = field(default_factory=list)

    # Subtitle
    subtitle_text: str = ""
    subtitle_visible: bool = True
    speaker_label: str = "AI主播"

    # Face frame (from avatar pipeline)
    face_frame: Optional[np.ndarray] = None   # BGR uint8 HWC

    # Background
    background: Optional[np.ndarray] = None   # BGR uint8 HWC, or None → dark bg

    # ── scene mode fields ───────────────────────────────────────────
    # When scene_mode=True, scene_rgba replaces the chart area.
    scene_rgba: Optional[np.ndarray] = None   # RGBA uint8 (H, W, 4) pre-rendered scene
    scene_label: str = ""                      # Current scene name for top bar display


# ── layout engine ───────────────────────────────────────────────────────

class LayoutEngine:
    """Compose a single livestream video frame from all data layers.

    Supports two modes:
        - Classic: chart 62% left + face 38% right + data panel
        - Scene:   face 25% left + scene content 75% right

    Usage::

        engine = LayoutEngine(config=LayoutConfig())
        frame_bgr = engine.compose(overlay_data)
        # frame_bgr.shape == (1080, 1920, 3)  BGR uint8
    """

    def __init__(self, config: LayoutConfig | None = None) -> None:
        self.cfg = config or LayoutConfig()
        self._init_renderers()

    def _init_renderers(self) -> None:
        """Initialize chart and subtitle renderers based on current config."""
        cfg = self.cfg
        if cfg.scene_mode:
            chart_w = int(cfg.width * (1.0 - cfg.face_width_ratio))
            chart_h = cfg.scene_main_area_height
        else:
            chart_w = cfg.chart_area_width
            chart_h = cfg.main_area_height

        self.chart_renderer = StockChartRenderer(
            figsize=(chart_w / cfg.chart_dpi, chart_h / cfg.chart_dpi),
            dpi=cfg.chart_dpi,
        )
        self.subtitle_renderer = SubtitleRenderer(
            font_size=34,
            bg_alpha=0.65,
        )
        self._small_sub = SubtitleRenderer(font_size=22, bg_alpha=0.3)
        self._bottom_sub = SubtitleRenderer(font_size=18, bg_alpha=0.4)

    def set_scene_mode(self, enabled: bool) -> None:
        """Toggle scene mode and reinitialize renderers."""
        if self.cfg.scene_mode != enabled:
            self.cfg.scene_mode = enabled
            self._init_renderers()

    # ── main compose ───────────────────────────────────────────────

    def compose(self, data: OverlayData) -> np.ndarray:
        """Compose a single frame.

        Returns BGR uint8 numpy array (height, width, 3).
        """
        import cv2

        w, h = self.cfg.width, self.cfg.height

        # ── Layer 0: Background ──
        if data.background is not None:
            canvas = cv2.resize(data.background, (w, h))
        else:
            canvas = np.full((h, w, 3), (13, 17, 23), dtype=np.uint8)  # dark BG

        if self.cfg.scene_mode:
            # Scene mode layout: face left 25% + scene right 75%
            self._draw_top_bar(canvas, data)
            self._draw_scene_area(canvas, data)
            self._draw_face_area_scene(canvas, data)
            self._draw_subtitle(canvas, data)
            self._draw_bottom_bar(canvas, data)
        else:
            # Classic layout
            self._draw_top_bar(canvas, data)
            self._draw_chart_area(canvas, data)
            self._draw_face_area(canvas, data)
            self._draw_data_panel(canvas, data)
            self._draw_subtitle(canvas, data)
            self._draw_bottom_bar(canvas, data)

        return canvas

    # ── layer drawing methods ──────────────────────────────────────

    def _draw_top_bar(self, canvas: np.ndarray, data: OverlayData) -> None:
        """Draw the top info bar."""
        import cv2

        cfg = self.cfg
        y1, y2 = 0, cfg.top_bar_height
        x1, x2 = 0, cfg.width

        # Semi-transparent dark panel
        overlay = canvas.copy()
        cv2.rectangle(overlay, (x1, y1), (x2, y2), (22, 27, 34), -1)
        canvas[:] = cv2.addWeighted(canvas, 0.6, overlay, 0.4, 0)

        # Bottom border
        cv2.line(canvas, (x1, y2), (x2, y2), (48, 54, 61), 2)

        # Stock info text
        color = ChartColors.GREEN if data.change_pct >= 0 else ChartColors.RED
        info_text = (
            f"{data.name} ({data.symbol})  |  "
            f"{data.price_now:.2f}  {data.change_pct:+.2f}%"
        )
        # Append scene label in scene mode
        if cfg.scene_mode and data.scene_label:
            info_text += f"  |  {data.scene_label}"

        # Render as RGBA strip and overlay
        info_rgba = self._small_sub.render(info_text, width=cfg.width - 40, height=cfg.top_bar_height,
                                           align="left", speaker_label="")
        self._overlay_rgba_region(canvas, info_rgba, 10, 0,
                                  cfg.width - 20, cfg.top_bar_height)

    def _draw_chart_area(self, canvas: np.ndarray, data: OverlayData) -> None:
        """Render K-line chart into the left portion."""
        import cv2

        cfg = self.cfg
        y1 = cfg.main_y_start
        chart_w = cfg.chart_area_width
        chart_h = cfg.main_area_height + cfg.data_panel_height  # chart spills into data panel

        # Render chart
        if data.kline_data:
            chart_rgba = self.chart_renderer.render_kline(
                symbol=data.symbol,
                name=data.name,
                kline_data=data.kline_data,
                fund_data=data.fund_data,
                price_now=data.price_now,
                change_pct=data.change_pct,
            )
            # Resize to fit chart area
            ch, cw = chart_rgba.shape[:2]
            scale = min(chart_w / cw, chart_h / ch)
            new_w = int(cw * scale)
            new_h = int(ch * scale)

            chart_bgr = cv2.cvtColor(chart_rgba[:, :, :3], cv2.COLOR_RGB2BGR)
            chart_bgr = cv2.resize(chart_bgr, (new_w, new_h))
            alpha = chart_rgba[:, :, 3:4].astype(np.float32) / 255.0
            alpha = cv2.resize(alpha, (new_w, new_h))
            if alpha.ndim == 2:
                alpha = np.expand_dims(alpha, axis=-1)

            # Place centered in chart area
            offset_x = (chart_w - new_w) // 2
            offset_y = (chart_h - new_h) // 2
            px = offset_x
            py = y1 + offset_y
            pw = min(new_w, canvas.shape[1] - px)
            ph = min(new_h, canvas.shape[0] - py)

            if pw > 0 and ph > 0:
                roi = canvas[py:py + ph, px:px + pw]
                blended = (chart_bgr[:ph, :pw] * alpha[:ph, :pw] + roi * (1.0 - alpha[:ph, :pw])).astype(np.uint8)
                canvas[py:py + ph, px:px + pw] = blended

        # Divider line between chart and face area
        x_div = cfg.chart_area_width
        cv2.line(canvas, (x_div, y1), (x_div, y1 + cfg.main_area_height),
                 (48, 54, 61), 1)

    def _draw_face_area(self, canvas: np.ndarray, data: OverlayData) -> None:
        """Place the digital human face into the right portion."""
        import cv2

        cfg = self.cfg
        face_x = cfg.face_area_x
        face_w = cfg.face_area_width
        y1 = cfg.main_y_start
        area_h = cfg.main_area_height

        # Face background - gradient dark panel
        overlay = canvas.copy()
        cv2.rectangle(overlay, (face_x, y1), (face_x + face_w, y1 + area_h),
                      (16, 20, 27), -1)
        canvas[:] = cv2.addWeighted(canvas, 0.5, overlay, 0.5, 0)

        # If we have a face frame, paste it
        if data.face_frame is not None:
            face_img = data.face_frame
            # Scale face to fit the face area with some padding
            target_w = int(face_w * cfg.face_scale)
            target_h = int(area_h * cfg.face_scale)
            aspect = face_img.shape[1] / max(face_img.shape[0], 1)
            if target_w / target_h > aspect:
                target_w = int(target_h * aspect)
            else:
                target_h = int(target_w / aspect)

            face_resized = cv2.resize(face_img, (target_w, target_h))

            # Center in face area
            fx = face_x + (face_w - target_w) // 2
            fy = y1 + cfg.face_y_offset + (area_h - target_h) // 2

            # Clamp to canvas
            fw_clamp = min(target_w, cfg.width - fx)
            fh_clamp = min(target_h, y1 + area_h - fy)

            if fw_clamp > 0 and fh_clamp > 0:
                canvas[fy:fy + fh_clamp, fx:fx + fw_clamp] = face_resized[:fh_clamp, :fw_clamp]

    def _draw_data_panel(self, canvas: np.ndarray, data: OverlayData) -> None:
        """Draw fund flow data strip at the bottom of the main area."""
        import cv2

        cfg = self.cfg
        y1 = cfg.data_panel_y
        y2 = y1 + cfg.data_panel_height
        panel_w = cfg.width

        # Background panel
        overlay = canvas.copy()
        cv2.rectangle(overlay, (0, y1), (panel_w, y2), (22, 27, 34), -1)
        canvas[:] = cv2.addWeighted(canvas, 0.5, overlay, 0.5, 0)
        cv2.line(canvas, (0, y1), (panel_w, y1), (48, 54, 61), 1)

        if data.fund_data:
            fund_rgba = self.chart_renderer.render_fund_flow_bars(
                data.fund_data,
                width_px=cfg.chart_area_width,
                height_px=cfg.data_panel_height,
            )
            # Overlay fund bars on the left (chart side)
            import cv2
            fund_bgr = cv2.cvtColor(fund_rgba[:, :, :3], cv2.COLOR_RGB2BGR)
            fund_bgr = cv2.resize(fund_bgr, (cfg.chart_area_width, cfg.data_panel_height))
            alpha = fund_rgba[:, :, 3:4].astype(np.float32) / 255.0
            alpha = cv2.resize(alpha, (cfg.chart_area_width, cfg.data_panel_height))
            if alpha.ndim == 2:
                alpha = np.expand_dims(alpha, axis=-1)
            roi = canvas[y1:y2, :cfg.chart_area_width]
            blended = (fund_bgr * alpha + roi * (1.0 - alpha)).astype(np.uint8)
            canvas[y1:y2, :cfg.chart_area_width] = blended

    def _draw_subtitle(self, canvas: np.ndarray, data: OverlayData) -> None:
        """Draw subtitle/caption bar."""
        if not data.subtitle_visible or not data.subtitle_text:
            return

        cfg = self.cfg
        y1 = cfg.subtitle_y
        sub_h = cfg.subtitle_height

        sub_rgba = self.subtitle_renderer.render(
            data.subtitle_text,
            width=cfg.width,
            height=sub_h,
            speaker_label=data.speaker_label,
        )
        self._overlay_rgba_region(canvas, sub_rgba, 0, y1, cfg.width, sub_h)

    def _draw_bottom_bar(self, canvas: np.ndarray, data: OverlayData) -> None:
        """Draw the bottom disclaimer bar."""
        import cv2

        cfg = self.cfg
        y1 = cfg.bottom_bar_y
        y2 = cfg.height

        overlay = canvas.copy()
        cv2.rectangle(overlay, (0, y1), (cfg.width, y2), (13, 17, 23), -1)
        canvas[:] = cv2.addWeighted(canvas, 0.6, overlay, 0.4, 0)
        cv2.line(canvas, (0, y1), (cfg.width, y1), (48, 54, 61), 1)

        bottom_text = "© StockStream AI 直播  |  内容仅供参考，不构成投资建议  |  投资有风险，入市需谨慎"
        bottom_rgba = self._bottom_sub.render_simple(
            bottom_text, width=cfg.width - 40, height=cfg.bottom_bar_height,
        )
        self._overlay_rgba_region(canvas, bottom_rgba, 20, y1, cfg.width - 40, cfg.bottom_bar_height)

    # ── scene mode drawing methods ─────────────────────────────────

    def _draw_scene_area(self, canvas: np.ndarray, data: OverlayData) -> None:
        """Draw the scene content on the right 75% area (scene mode)."""
        import cv2

        cfg = self.cfg
        sx = cfg.scene_area_x
        sy = cfg.main_y_start
        sw = cfg.chart_area_width  # in scene mode = 75% of width
        sh = cfg.effective_main_height

        # Background panel
        overlay = canvas.copy()
        cv2.rectangle(overlay, (sx, sy), (sx + sw, sy + sh), (16, 20, 27), -1)
        canvas[:] = cv2.addWeighted(canvas, 0.5, overlay, 0.5, 0)

        # Divider line between face and scene
        cv2.line(canvas, (sx, sy), (sx, sy + sh), (48, 54, 61), 2)

        # Render scene content
        if data.scene_rgba is not None:
            scene_h, scene_w = scene_rgba.shape[:2] if (scene_rgba := data.scene_rgba) is not None else (0, 0)
            if data.scene_rgba is not None:
                scene_rgba = data.scene_rgba
                sh_rgba, sw_rgba = scene_rgba.shape[:2]

                # Scale to fit scene area preserving aspect ratio
                scale = min(sw / sw_rgba, sh / sh_rgba)
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

                # Center in scene area
                offset_x = (sw - new_w) // 2
                offset_y = (sh - new_h) // 2
                px = sx + offset_x
                py = sy + offset_y
                pw = min(new_w, canvas.shape[1] - px)
                ph = min(new_h, canvas.shape[0] - py)

                if pw > 0 and ph > 0:
                    roi = canvas[py:py + ph, px:px + pw]
                    blended = (scene_bgr[:ph, :pw] * alpha[:ph, :pw] +
                               roi * (1.0 - alpha[:ph, :pw])).astype(np.uint8)
                    canvas[py:py + ph, px:px + pw] = blended

    def _draw_face_area_scene(self, canvas: np.ndarray, data: OverlayData) -> None:
        """Place the digital human face on the left 25% area (scene mode)."""
        import cv2

        cfg = self.cfg
        face_x = 0
        face_w = cfg.face_area_width
        y1 = cfg.main_y_start
        area_h = cfg.effective_main_height

        # Face background gradient
        overlay = canvas.copy()
        cv2.rectangle(overlay, (face_x, y1), (face_x + face_w, y1 + area_h),
                      (16, 20, 27), -1)
        canvas[:] = cv2.addWeighted(canvas, 0.5, overlay, 0.5, 0)

        # Scene label on top of face area
        if data.scene_label:
            label_rgba = self._small_sub.render(
                data.scene_label, width=face_w - 10, height=28,
                align="center", speaker_label="",
            )
            self._overlay_rgba_region(canvas, label_rgba, 5, y1 + 5, face_w - 10, 28)

        # Face frame
        if data.face_frame is not None:
            face_img = data.face_frame
            target_w = int(face_w * cfg.face_scale)
            target_h = int(area_h * cfg.face_scale)
            aspect = face_img.shape[1] / max(face_img.shape[0], 1)
            if target_w / target_h > aspect:
                target_w = int(target_h * aspect)
            else:
                target_h = int(target_w / aspect)

            face_resized = cv2.resize(face_img, (target_w, target_h))
            fx = face_x + (face_w - target_w) // 2
            fy = y1 + 40 + (area_h - 40 - target_h) // 2

            fw_clamp = min(target_w, cfg.width - fx)
            fh_clamp = min(target_h, y1 + area_h - fy)

            if fw_clamp > 0 and fh_clamp > 0:
                canvas[fy:fy + fh_clamp, fx:fx + fw_clamp] = face_resized[:fh_clamp, :fw_clamp]

    # ── utility ────────────────────────────────────────────────────

    @staticmethod
    def _overlay_rgba_region(
        canvas: np.ndarray,      # BGR uint8 (H, W, 3)
        rgba: np.ndarray,        # RGBA uint8 (h, w, 4)
        x: int, y: int,
        w: int, h: int,
    ) -> None:
        """Overlay an RGBA image onto a canvas region."""
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


# ── factory ─────────────────────────────────────────────────────────────

def create_default_engine() -> LayoutEngine:
    """Create a LayoutEngine with stock livestream defaults."""
    return LayoutEngine(LayoutConfig())
