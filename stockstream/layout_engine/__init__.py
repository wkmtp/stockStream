"""Layout engine — composes the full 1920x1080 livestream frame.

Defines named layout presets (live, scene, classic) and renders each
region independently, supporting dynamic layout switching at runtime.

Regions (1920×1080):

    ┌─────────────────────────────────────────────────────────────┐
    │  Title Bar (top)                                   h: 80px  │
    ├──────────────┬──────────────────────────────────────────────┤
    │              │                                              │
    │  Digital     │   Chart / Scene Area                         │
    │  Human       │   width: 1440px                              │
    │  width:480px │                                              │
    │              │                                              │
    ├──────────────┴──────────────────────────────────────────────┤
    │  Subtitle Bar (bottom)                           h: 120px   │
    └─────────────────────────────────────────────────────────────┘

Usage::

    from stockstream.layout_engine import LayoutEngine, LayoutConfig, LivePreset
    engine = LayoutEngine(LivePreset)
    engine.switch_layout("scene")   # dynamic switch
    frame_bgr = engine.compose(overlay_data)
"""

from stockstream.layout_engine.models import (
    LayoutConfig,
    LayoutPreset,
    OverlayData,
    RegionRect,
    LivePreset,
    ScenePreset,
    ClassicPreset,
    PRESETS,
)
from stockstream.layout_engine.engine import (
    LayoutEngine,
    create_layout_engine,
)
from stockstream.layout_engine.regions import (
    TitleBarRenderer,
    DigitalHumanRenderer,
    ChartRenderer,
    SubtitleRenderer as LayoutSubtitleRenderer,
)

__all__ = [
    "LayoutConfig",
    "LayoutPreset",
    "OverlayData",
    "RegionRect",
    "LivePreset",
    "ScenePreset",
    "ClassicPreset",
    "PRESETS",
    "LayoutEngine",
    "create_layout_engine",
    "TitleBarRenderer",
    "DigitalHumanRenderer",
    "ChartRenderer",
    "LayoutSubtitleRenderer",
]
