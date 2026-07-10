"""AI Slide Generator — auto-generates financial PPT-style PNG pages from stock selection results.

Converts SelectorReport signals into professionally styled financial presentation
slides for digital human livestream scene switching.

Slide types:
    - 建仓推荐 (open_position)  — Top buy candidates with entry reasons
    - 补仓推荐 (add_position)   — Top add-position candidates with reasons
    - 减仓提示 (reduce_position) — Reduce-position warnings
    - 清仓提示 (clear_position)  — Clear-position alerts
    - 风险提示 (risk_warning)     — Risk disclosure card

Output: PNG RGBA uint8 numpy arrays, ready for compositing into 1920×1080 frames.
"""

from stockstream.ai_slide_generator.generator import SlideGenerator, create_slide_generator
from stockstream.ai_slide_generator.models import (
    SlideData,
    SlideConfig,
    SlideType,
    SlideTemplate,
    OpenPositionSlide,
    AddPositionSlide,
    ReducePositionSlide,
    ClearPositionSlide,
    RiskWarningSlide,
    SlideResult,
)
from stockstream.ai_slide_generator.presets import (
    SLIDE_TEMPLATES,
    SLIDE_PRESETS,
    get_template,
)

__all__ = [
    "SlideGenerator",
    "create_slide_generator",
    "SlideData",
    "SlideConfig",
    "SlideType",
    "SlideTemplate",
    "OpenPositionSlide",
    "AddPositionSlide",
    "ReducePositionSlide",
    "ClearPositionSlide",
    "RiskWarningSlide",
    "SlideResult",
    "SLIDE_TEMPLATES",
    "SLIDE_PRESETS",
    "get_template",
]
