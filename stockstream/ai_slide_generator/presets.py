"""Slide presets — named template registry and helper utilities.

Pre-configured slide templates for each stock selection signal type:

    SLIDE_TEMPLATES: dict[SlideType, SlideTemplate]
        Maps each SlideType to its visual template (colours, layout hints).

    SLIDE_PRESETS: dict[str, SlideTemplate]
        String-keyed convenience access (same as SLIDE_TEMPLATES but
        keyed by string value).

    get_template(name) → SlideTemplate
        Look up a template by SlideType or string name.
"""

from __future__ import annotations

from typing import Union

from stockstream.ai_slide_generator.models import (
    SlideType,
    SlideTemplate,
    OpenPositionSlide,
    AddPositionSlide,
    ReducePositionSlide,
    ClearPositionSlide,
    RiskWarningSlide,
)


# ── Template registry ───────────────────────────────────────────────────

SLIDE_TEMPLATES: dict[SlideType, SlideTemplate] = {
    SlideType.OPEN_POSITION: OpenPositionSlide,
    SlideType.ADD_POSITION: AddPositionSlide,
    SlideType.REDUCE_POSITION: ReducePositionSlide,
    SlideType.CLEAR_POSITION: ClearPositionSlide,
    SlideType.RISK_WARNING: RiskWarningSlide,
}


# ── String-keyed presets ────────────────────────────────────────────────

SLIDE_PRESETS: dict[str, SlideTemplate] = {
    "open_position": OpenPositionSlide,
    "add_position": AddPositionSlide,
    "reduce_position": ReducePositionSlide,
    "clear_position": ClearPositionSlide,
    "risk_warning": RiskWarningSlide,
}


def get_template(name: Union[str, SlideType]) -> SlideTemplate:
    """Look up a slide template by name or SlideType.

    Args:
        name: SlideType enum value, SlideType instance, or string key.

    Returns:
        SlideTemplate for the given type.

    Raises:
        KeyError: if the template name is unknown.
    """
    if isinstance(name, SlideType):
        return SLIDE_TEMPLATES[name]

    # Try string lookup
    key = name.lower() if isinstance(name, str) else str(name)
    if key in SLIDE_PRESETS:
        return SLIDE_PRESETS[key]

    # Try SlideType enum value lookup
    try:
        st = SlideType(key)
        return SLIDE_TEMPLATES[st]
    except ValueError:
        pass

    # Fallback to risk warning
    return RiskWarningSlide
