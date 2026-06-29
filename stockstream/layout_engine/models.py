"""Layout engine data models — configuration, regions, and overlay data."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np


# ── Region rectangle ─────────────────────────────────────────────────────

@dataclass()
class RegionRect:
    """A rectangular region in the 1920×1080 frame."""

    x: int
    y: int
    width: int
    height: int

    @property
    def x2(self) -> int:
        return self.x + self.width

    @property
    def y2(self) -> int:
        return self.y + self.height

    def to_tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)


# ── Layout preset ────────────────────────────────────────────────────────

class LayoutPreset(str, Enum):
    """Named layout presets."""

    LIVE = "live"        # default: face-left(480) + chart-right(1440) + subtitle-bottom(120)
    SCENE = "scene"      # face-left(25%) + scene-right(75%) + subtitle-bottom(120)
    CLASSIC = "classic"  # chart-left(62%) + face-right(38%) + data-panel + subtitle-bottom(80)


@dataclass()
class LayoutConfig:
    """Layout geometry for one preset.

    All measurements in pixels at 1920×1080.
    """

    # ── frame ──
    width: int = 1920
    height: int = 1080

    # ── top title bar ──
    title_bar_height: int = 80

    # ── digital human (left) ──
    face_width: int = 480         # digital human region width
    face_x: int = 0               # always left edge

    # ── chart/scene area (right) ──
    chart_width: int = 1440       # chart region width (width - face_width)
    chart_x: int = 480            # starts after face region

    # ── bottom subtitle bar ──
    subtitle_height: int = 120

    # ── internal spacing ──
    main_area_height: int = 880   # height between title_bar and subtitle (1080-80-120)

    # ── face sizing ──
    face_scale: float = 0.78      # face image scale within face region
    face_y_offset: int = 20       # px from top of main area

    # ── chart DPI ──
    chart_dpi: int = 100

    # ── computed properties ──

    @property
    def title_bar_rect(self) -> RegionRect:
        return RegionRect(0, 0, self.width, self.title_bar_height)

    @property
    def face_rect(self) -> RegionRect:
        return RegionRect(self.face_x, self.title_bar_height,
                          self.face_width, self.main_area_height)

    @property
    def chart_rect(self) -> RegionRect:
        return RegionRect(self.chart_x, self.title_bar_height,
                          self.chart_width, self.main_area_height)

    @property
    def subtitle_rect(self) -> RegionRect:
        return RegionRect(0, self.title_bar_height + self.main_area_height,
                          self.width, self.subtitle_height)

    @property
    def main_y_start(self) -> int:
        return self.title_bar_height

    @property
    def subtitle_y(self) -> int:
        return self.title_bar_height + self.main_area_height

    def region(self, name: str) -> RegionRect:
        """Get a named region rect."""
        mapping = {
            "title_bar": self.title_bar_rect,
            "face": self.face_rect,
            "chart": self.chart_rect,
            "subtitle": self.subtitle_rect,
        }
        return mapping.get(name, RegionRect(0, 0, self.width, self.height))


# ── Overlay data ─────────────────────────────────────────────────────────

@dataclass
class OverlayData:
    """Dynamic data for one frame of the livestream."""

    # ── stock info ──
    symbol: str = ""
    name: str = ""
    price_now: float = 0.0
    change_pct: float = 0.0

    # ── chart data ──
    kline_data: list[dict] = field(default_factory=list)
    fund_data: list[dict] = field(default_factory=list)

    # ── subtitle ──
    subtitle_text: str = ""
    subtitle_visible: bool = True
    speaker_label: str = "AI主播"

    # ── digital human face ──
    face_frame: Optional[np.ndarray] = None   # BGR uint8 HWC

    # ── background ──
    background: Optional[np.ndarray] = None   # BGR uint8 HWC

    # ── scene mode (pre-rendered content for chart area) ──
    scene_rgba: Optional[np.ndarray] = None   # RGBA uint8 (H, W, 4)
    scene_label: str = ""

    # ── title bar extras ──
    title_extra: str = ""   # e.g. scene name, status


# ── Preset factory ───────────────────────────────────────────────────────

LivePreset = LayoutConfig(
    face_width=480,
    face_x=0,
    chart_width=1440,
    chart_x=480,
    title_bar_height=80,
    subtitle_height=120,
    main_area_height=880,
    face_scale=0.78,
)

ScenePreset = LayoutConfig(
    face_width=480,
    face_x=0,
    chart_width=1440,
    chart_x=480,
    title_bar_height=80,
    subtitle_height=120,
    main_area_height=880,
    face_scale=0.75,
)

ClassicPreset = LayoutConfig(
    face_width=730,         # 38% of 1920
    face_x=1190,            # after chart (62%)
    chart_width=1190,       # 62% of 1920
    chart_x=0,
    title_bar_height=60,
    subtitle_height=80,
    main_area_height=940,   # 1080 - 60 - 80
    face_scale=0.75,
)

PRESETS: dict[str, LayoutConfig] = {
    "live": LivePreset,
    "scene": ScenePreset,
    "classic": ClassicPreset,
}
