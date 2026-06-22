"""Subtitle engine — real-time SRT + transparent PNG subtitle layer generation.

Receives digital human narration text (e.g. from TTS callbacks), and produces:
  - subtitle.srt           — word-synchronised SRT subtitle file
  - subtitle_<id>.png      — transparent PNG overlay strips for FFmpeg compositing

Architecture::

    TTS sentence text
         │
         ▼
    SubtitleEngine.receive(text)
         │
         ├──► TimingEngine    →  estimate per-word timestamps (based on char count)
         ├──► SrtWriter       →  generate SRT file (word-level sync)
         └──► PngRenderer     →  generate transparent PNG strips (逐字逐句)
              │
              ▼
         cache/subtitle/
"""

from stockstream.subtitle_engine.engine import SubtitleEngine, create_subtitle_engine
from stockstream.subtitle_engine.models import (
    SrtEntry,
    SubtitleTrack,
    SubtitleWord,
    SubtitleStyle,
)

__all__ = [
    "SubtitleEngine",
    "create_subtitle_engine",
    "SrtEntry",
    "SubtitleTrack",
    "SubtitleWord",
    "SubtitleStyle",
]
