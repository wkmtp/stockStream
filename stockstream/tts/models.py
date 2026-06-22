"""TTS data models — voice configs, tasks, results, and sentence units."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TTSEngine(str, Enum):
    """Backend TTS engine."""
    PIPER = "piper"       # Local neural TTS (Piper)
    NONE = "none"         # No engine (dry-run / placeholder)


class TTSStatus(str, Enum):
    """Task execution status."""
    PENDING = "pending"
    SYNTHESIZING = "synthesizing"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"   # Empty sentence


@dataclass(slots=True)
class TTSVoice:
    """Piper voice configuration."""
    name: str = "zh_CN-huayan-medium"
    model_path: str = ""
    config_path: str = ""
    sample_rate: int = 22050
    # Piper CLI extra args: --length_scale, --noise_scale, --noise_w, --sentence_silence
    length_scale: float = 1.0
    noise_scale: float = 0.667
    noise_w: float = 0.8
    sentence_silence: float = 0.2

    def cli_args(self) -> list[str]:
        """Build Piper CLI arguments for this voice."""
        args = [
            "--model", self.model_path or self.name,
            "--length_scale", str(self.length_scale),
            "--noise_scale", str(self.noise_scale),
            "--noise_w", str(self.noise_w),
            "--sentence_silence", str(self.sentence_silence),
        ]
        return args


@dataclass(slots=True)
class Sentence:
    """A single sentence fragment ready for synthesis."""
    index: int
    text: str
    char_count: int = 0

    def __post_init__(self) -> None:
        if not self.char_count:
            self.char_count = len(self.text)


@dataclass(slots=True)
class TTSTask:
    """A TTS task submitted for synthesis."""
    task_id: str
    text: str
    voice: TTSVoice | None = None
    created_at: float = field(default_factory=time.monotonic)
    sentences: list[Sentence] = field(default_factory=list)
    status: TTSStatus = TTSStatus.PENDING
    wav_paths: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def progress(self) -> tuple[int, int]:
        """Return (done, total) sentence counts."""
        total = len(self.sentences)
        done = len(self.wav_paths)
        return done, total

    def to_dict(self) -> dict[str, Any]:
        done, total = self.progress
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "progress": f"{done}/{total}",
            "sentence_count": total,
            "wav_paths": self.wav_paths,
            "error": self.error,
            "char_count": len(self.text),
        }


@dataclass(slots=True)
class TTSPlayEvent:
    """Emitted after each sentence is synthesized, for live playback."""
    task_id: str
    sentence_index: int
    sentence_text: str
    wav_path: str        # Path to synthesized WAV file
    is_last: bool = False
    timestamp: float = field(default_factory=time.monotonic)
