"""Layout presets — predefined layout configurations for different use cases.

Presets:
    live    — default streaming: face-left(480) + chart-right(1440) + subtitle(120)
    scene   — scene-aware streaming: face-left(480) + scene-right(1440) + subtitle(120)
    classic — traditional: chart-left(1190) + face-right(730) + data-panel + subtitle(80)

Each preset defines the exact pixel positions of the four regions
within the 1920×1080 frame.

Live preset (default):
    ┌─────────────────────────────────────────────────────────────┐  0
    │  Title Bar (80px)                                          │
    ├──────────────┬──────────────────────────────────────────────┤
    │  Digital     │  Chart Area (1440px)                         │
    │  Human       │                                              │
    │  (480px)     │                                              │
    │              │                                              │  960
    ├──────────────┴──────────────────────────────────────────────┤
    │  Subtitle Bar (120px)                                       │
    └─────────────────────────────────────────────────────────────┘  1080

Classic preset:
    ┌─────────────────────────────────────────────────────────────┐  0
    │  Title Bar (60px)                                          │
    ├─────────────────────────────────────┬───────────────────────┤
    │                                     │                       │
    │   Chart Area (1190px)               │  Digital Human        │
    │                                     │  (730px)              │
    │                                     │                       │  940
    ├─────────────────────────────────────┴───────────────────────┤
    │  Subtitle Bar (80px)                                        │
    └─────────────────────────────────────────────────────────────┘  1080
"""

from __future__ import annotations

from stockstream.layout_engine.models import (
    LayoutConfig,
    LayoutPreset,
    LivePreset,
    ScenePreset,
    ClassicPreset,
    PRESETS,
)

__all__ = [
    "LayoutConfig",
    "LayoutPreset",
    "LivePreset",
    "ScenePreset",
    "ClassicPreset",
    "PRESETS",
]
