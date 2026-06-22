"""Avatar data models — tasks, configs, results for Wav2Lip talking-head generation.

Pipeline::

    TTS audio (.wav) + host image (.jpg/.png)
        │
        ▼
    AudioProcessor   ──► mel spectrogram (80-bin, 16kHz)
    FaceDetector     ──► face bbox + landmarks
        │
        ▼
    Wav2LipONNX      ──► lip-synced face frames (96x96)
        │
        ▼
    VideoAssembler   ──► MP4 (H.264 + AAC)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


# ═══════════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════════


class AvatarStatus(str, Enum):
    """Avatar task execution status."""
    PENDING = "pending"
    DETECTING = "detecting"
    SYNTHESIZING = "synthesizing"
    ASSEMBLING = "assembling"
    DONE = "done"
    FAILED = "failed"


# ═══════════════════════════════════════════════════════════════════
# Face detection result
# ═══════════════════════════════════════════════════════════════════


@dataclass(slots=True)
class FaceBox:
    """Detected face bounding box + landmarks."""
    x: int
    y: int
    width: int
    height: int
    confidence: float = 1.0
    landmarks: list[tuple[float, float]] = field(default_factory=list)

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)

    def expand(self, scale: float = 1.5) -> FaceBox:
        """Expand box by a scale factor (used before Wav2Lip crop)."""
        cx, cy = self.center
        new_w = int(self.width * scale)
        new_h = int(self.height * scale)
        return FaceBox(
            x=max(0, cx - new_w // 2),
            y=max(0, cy - new_h // 2),
            width=new_w,
            height=new_h,
            confidence=self.confidence,
            landmarks=self.landmarks,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "x": self.x, "y": self.y,
            "width": self.width, "height": self.height,
            "confidence": self.confidence,
            "center": list(self.center),
        }


# ═══════════════════════════════════════════════════════════════════
# Audio processing result
# ═══════════════════════════════════════════════════════════════════


@dataclass(slots=True)
class MelSpectrogram:
    """Mel spectrogram extracted from WAV audio for Wav2Lip input.

    Shape: (num_frames, 80)  where num_frames = T / hop_length.
    Sample rate is resampled to 16 kHz internally.
    """
    mel: "np.ndarray"  # noqa: F821  shape (T_mel, 80)
    sample_rate: int = 16000
    hop_length: int = 200       # 12.5 ms at 16 kHz
    win_length: int = 800       # 50 ms
    n_mels: int = 80
    duration_s: float = 0.0

    @property
    def num_frames(self) -> int:
        return self.mel.shape[0]


# ═══════════════════════════════════════════════════════════════════
# Wav2Lip inference config
# ═══════════════════════════════════════════════════════════════════


@dataclass(slots=True)
class AvatarConfig:
    """Wav2Lip ONNX model paths and generation parameters."""

    # ── model paths ──
    face_detector_onnx: str = "models/face_detector.onnx"
    wav2lip_generator_onnx: str = "models/wav2lip_gan.onnx"

    # ── generator parameters ──
    img_size: int = 96                    # Wav2Lip face crop size
    mel_step_size: int = 16               # mel frames per generator step
    fps: int = 25                         # output video FPS
    face_batch_size: int = 128            # frames per inference batch

    # ── face detection ──
    face_det_threshold: float = 0.5       # minimum detection confidence
    face_expand_scale: float = 1.5        # how much to expand the face box

    # ── output ──
    output_fps: int = 25
    output_codec: str = "libx264"
    output_pix_fmt: str = "yuv420p"
    output_crf: int = 23
    temp_dir: str = "data/avatar_temp"

    @property
    def mel_channels(self) -> int:
        return 80

    @property
    def mel_frames_per_step(self) -> int:
        return self.mel_step_size  # typically 16


# ═══════════════════════════════════════════════════════════════════
# Avatar task & result
# ═══════════════════════════════════════════════════════════════════


@dataclass(slots=True)
class AvatarTask:
    """A single avatar generation task — image + audio → MP4."""

    task_id: str
    image_path: str                      # path to host image (.jpg/.png)
    audio_path: str                      # path to Piper TTS WAV file
    output_path: str = ""                # destination MP4 path
    config: AvatarConfig = field(default_factory=AvatarConfig)
    status: AvatarStatus = AvatarStatus.PENDING
    created_at: float = field(default_factory=time.monotonic)
    error: str = ""
    # result
    total_frames: int = 0
    duration_s: float = 0.0
    face_box: FaceBox | None = None

    @property
    def progress_pct(self) -> float:
        if self.total_frames == 0:
            return 0.0
        # updated incrementally by the pipeline
        return getattr(self, "_frames_done", 0) / max(1, self.total_frames) * 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "image_path": self.image_path,
            "audio_path": self.audio_path,
            "output_path": self.output_path,
            "total_frames": self.total_frames,
            "duration_s": self.duration_s,
            "progress_pct": round(self.progress_pct, 1),
            "error": self.error,
        }


@dataclass(slots=True)
class AvatarResult:
    """Completed avatar generation result."""

    task_id: str
    output_path: str                     # absolute path to MP4
    duration_s: float
    total_frames: int
    width: int = 1920
    height: int = 1080
    file_size_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "output_path": self.output_path,
            "duration_s": self.duration_s,
            "total_frames": self.total_frames,
            "resolution": f"{self.width}x{self.height}",
            "file_size_mb": round(self.file_size_bytes / (1024 * 1024), 2),
        }
