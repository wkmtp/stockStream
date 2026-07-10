"""Subtitle engine data models — SRT entries, word-level timing, track aggregates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass()
class SubtitleStyle:
    """Visual styling for PNG subtitle rendering."""

    font_size: int = 36
    text_color: tuple[int, int, int] = (255, 255, 255)       # white
    highlight_color: tuple[int, int, int] = (255, 215, 0)    # gold for active word
    bg_color: tuple[int, int, int] = (0, 0, 0)               # black
    bg_alpha: float = 0.55
    padding: int = 12
    # PNG dimensions
    width: int = 1920
    height: int = 80
    # Active word highlight mode
    highlight_active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "font_size": self.font_size,
            "text_color": list(self.text_color),
            "highlight_color": list(self.highlight_color),
            "bg_color": list(self.bg_color),
            "bg_alpha": self.bg_alpha,
            "width": self.width,
            "height": self.height,
            "highlight_active": self.highlight_active,
        }


@dataclass()
class SubtitleWord:
    """A single word/character with its timing window."""

    text: str
    start_ms: int          # absolute start in milliseconds from track origin
    end_ms: int            # absolute end in milliseconds

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


@dataclass()
class SrtEntry:
    """One SRT subtitle entry (one line / short segment).

    SRT format::

        1
        00:00:01,000 --> 00:00:02,500
        贵州茅台今日主力资金净流入2.1亿
    """

    index: int
    start_ms: int
    end_ms: int
    text: str

    def to_srt_lines(self) -> str:
        """Render this entry as SRT block text (without trailing blank line)."""
        return (
            f"{self.index}\n"
            f"{_ms_to_srt_time(self.start_ms)} --> {_ms_to_srt_time(self.end_ms)}\n"
            f"{self.text}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "start_srt": _ms_to_srt_time(self.start_ms),
            "end_srt": _ms_to_srt_time(self.end_ms),
            "text": self.text,
        }


@dataclass()
class SubtitleTrack:
    """A complete subtitle track for one narration text.

    Contains word-level entries for SRT generation and per-frame PNG rendering.
    """

    task_id: str                           # unique ID for this subtitle task
    full_text: str                         # original full narration text
    words: list[SubtitleWord] = field(default_factory=list)
    entries: list[SrtEntry] = field(default_factory=list)
    total_duration_ms: int = 0
    srt_path: str = ""
    png_dir: str = ""

    @property
    def entry_count(self) -> int:
        return len(self.entries)

    @property
    def word_count(self) -> int:
        return len(self.words)

    @property
    def has_content(self) -> bool:
        return len(self.entries) > 0 and len(self.words) > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "full_text": self.full_text,
            "word_count": self.word_count,
            "entry_count": self.entry_count,
            "total_duration_ms": self.total_duration_ms,
            "total_duration_sec": round(self.total_duration_ms / 1000, 2),
            "srt_path": self.srt_path,
            "png_dir": self.png_dir,
            "words": [{"text": w.text, "start_ms": w.start_ms, "end_ms": w.end_ms}
                      for w in self.words],
            "entries": [e.to_dict() for e in self.entries],
        }


# ── helpers ──────────────────────────────────────────────────────────────

def _ms_to_srt_time(ms: int) -> str:
    """Convert milliseconds to SRT time format HH:MM:SS,mmm."""
    hours = ms // 3_600_000
    ms %= 3_600_000
    minutes = ms // 60_000
    ms %= 60_000
    seconds = ms // 1_000
    millis = ms % 1_000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"
