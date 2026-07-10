"""Real-time video compositing layer for StockStream digital human livestream.

Pipelines:
    chart_renderer.py      — K-line, price, volume, fund-flow charts as numpy arrays
    indicator_renderer.py  — MACD, RSI, dragon-tiger, sector heatmap, AI summary cards
    subtitle_renderer.py   — Chinese subtitle text overlay with audio sync
    layout_engine.py       — [legacy] layout engine (kept for compositor compat)
    scene_manager.py       — Smart scene engine: auto-match background to spoken content
    compositor.py          — Live pipeline: frames → FFmpeg pipe → RTMP push

New layout_engine module (preferred):
    stockstream.layout_engine — full layout engine with presets, dynamic switching
"""

from stockstream.video.chart_renderer import StockChartRenderer, ChartColors
from stockstream.video.subtitle_renderer import SubtitleRenderer
from stockstream.video.layout_engine import LayoutEngine, LayoutConfig, OverlayData
from stockstream.video.compositor import LiveCompositor, CompositorConfig, PreRenderCompositor, CompositorState
from stockstream.video.scene_manager import (
    SceneManager,
    SceneType,
    SceneData,
    create_scene_manager,
)
from stockstream.video.indicator_renderer import (
    render_macd,
    render_rsi,
    render_volume_standalone,
    render_dragon_tiger,
    render_sector_heatmap,
    render_advance_decline,
    render_ai_summary_card,
)

# Re-export new layout engine for convenience
from stockstream.layout_engine.engine import LayoutEngine as NewLayoutEngine
from stockstream.layout_engine.engine import create_layout_engine
from stockstream.layout_engine.models import LayoutConfig as NewLayoutConfig
from stockstream.layout_engine.models import OverlayData as NewOverlayData
from stockstream.layout_engine.models import LayoutPreset, LivePreset, ScenePreset, ClassicPreset, PRESETS

__all__ = [
    # Chart
    "StockChartRenderer",
    "ChartColors",
    # Subtitles
    "SubtitleRenderer",
    # Layout (legacy)
    "LayoutEngine",
    "LayoutConfig",
    "OverlayData",
    # Layout (new — preferred)
    "NewLayoutEngine",
    "NewLayoutConfig",
    "NewOverlayData",
    "create_layout_engine",
    "LayoutPreset",
    "LivePreset",
    "ScenePreset",
    "ClassicPreset",
    "PRESETS",
    # Compositing
    "LiveCompositor",
    "CompositorConfig",
    "PreRenderCompositor",
    "CompositorState",
    # Scene Engine
    "SceneManager",
    "SceneType",
    "SceneData",
    "create_scene_manager",
    # Indicator Renderers
    "render_macd",
    "render_rsi",
    "render_volume_standalone",
    "render_dragon_tiger",
    "render_sector_heatmap",
    "render_advance_decline",
    "render_ai_summary_card",
]
