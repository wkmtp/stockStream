"""tts_alignment data models — word-level alignment results."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class AlignmentMethod(str, enum.Enum):
    """Which alignment backend was used."""
    AENEAS = "aeneas"           # forced alignment via aeneas + espeak-ng
    WAV_PROPORTIONAL = "wav"    # WAV duration + proportional distribution
    CHAR_COUNT = "chars"        # pure character-count estimation (last resort)


@dataclass(slots=True)
class AlignmentWord:
    """A single aligned word/character with its timing window.

    This is the fundamental output unit: one timestamp per character
    (or per word-group for multi-character words like "茅台").
    """

    text: str               # the word/character text (e.g. "贵", "州", "茅台")
    start_sec: float        # absolute start time in seconds
    end_sec: float          # absolute end time in seconds

    @property
    def start_ms(self) -> int:
        return int(self.start_sec * 1000)

    @property
    def end_ms(self) -> int:
        return int(self.end_sec * 1000)

    @property
    def duration_sec(self) -> float:
        return self.end_sec - self.start_sec

    @property
    def duration_ms(self) -> int:
        return int(self.duration_sec * 1000)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "start_sec": round(self.start_sec, 3),
            "end_sec": round(self.end_sec, 3),
            "duration_sec": round(self.duration_sec, 3),
        }


@dataclass(slots=True)
class AlignmentResult:
    """Complete forced-alignment result for one text+audio pair.

    Core output: ``timestamps`` — a flat dict of {word_text: start_sec}.

    Example::

        {
            "贵": 0.00,
            "州": 0.12,
            "茅": 0.24,
            "台": 0.36,
            "今": 0.52,
            ...
        }
    """

    text: str                               # original input text
    wav_path: str                           # path to the audio file used
    method: AlignmentMethod                 # which backend produced this result
    words: list[AlignmentWord] = field(default_factory=list)
    total_duration_sec: float = 0.0
    # Per-word timestamps: {word_text: start_sec}
    timestamps: dict[str, float] = field(default_factory=dict)
    # Per-character timestamps (one per char): {"贵": 0.0, "州": 0.12, ...}
    char_timestamps: dict[str, float] = field(default_factory=dict)
    # Metadata
    confidence: float = 0.0                 # 0.0–1.0 (aeneas: DTW confidence; fallback: 0.5)
    error: str = ""

    @property
    def word_count(self) -> int:
        return len(self.words)

    @property
    def total_duration_ms(self) -> int:
        return int(self.total_duration_sec * 1000)

    @property
    def has_content(self) -> bool:
        return len(self.words) > 0 and self.total_duration_sec > 0

    def get_char_at_time(self, time_sec: float) -> AlignmentWord | None:
        """Return the word/char active at a given time point."""
        for w in self.words:
            if w.start_sec <= time_sec < w.end_sec:
                return w
        return None

    def get_active_index(self, time_sec: float) -> int:
        """Return the index of the word active at time_sec, or -1."""
        for i, w in enumerate(self.words):
            if w.start_sec <= time_sec < w.end_sec:
                return i
        return -1

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "wav_path": self.wav_path,
            "method": self.method.value,
            "confidence": round(self.confidence, 3),
            "word_count": self.word_count,
            "total_duration_sec": round(self.total_duration_sec, 3),
            "total_duration_ms": self.total_duration_ms,
            "error": self.error,
            "timestamps": {k: round(v, 3) for k, v in self.timestamps.items()},
            "char_timestamps": {k: round(v, 3) for k, v in self.char_timestamps.items()},
            "words": [w.to_dict() for w in self.words],
        }
