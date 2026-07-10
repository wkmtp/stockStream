"""tts_alignment — forced alignment engine for word-level timestamping.

Given Piper TTS audio + original text, produces per-word timestamps for
subtitle synchronisation.

Backends (priority order):
  1. aeneas (forced alignment via espeak-ng synthesis)
  2. WAV-duration proportional distribution (fallback)

Output format::

    {"贵州": 0.10, "茅台": 0.52, "今日": 1.05, ...}

Usage::

    from stockstream.tts_alignment import AlignmentEngine, create_alignment_engine

    engine = create_alignment_engine()
    await engine.start()

    result = await engine.align(
        text="贵州茅台今日主力资金净流入2.1亿",
        wav_path="data/tts/xxx.wav",
    )
    # result.timestamps → {"贵州": 0.10, "茅台": 0.52, "今日": 1.05, ...}
    # result.words → [SubtitleWord("贵", 0, 100), SubtitleWord("州", 100, 200), ...]
"""

from __future__ import annotations

from stockstream.tts_alignment.models import (
    AlignmentResult,
    AlignmentWord,
    AlignmentMethod,
)
from stockstream.tts_alignment.engine import (
    AlignmentEngine,
    create_alignment_engine,
)

__all__ = [
    "AlignmentResult",
    "AlignmentWord",
    "AlignmentMethod",
    "AlignmentEngine",
    "create_alignment_engine",
]
