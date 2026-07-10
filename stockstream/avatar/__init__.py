"""Avatar module — Wav2Lip talking-head video generation.

Pipeline::

    host image  +  Piper TTS audio (WAV)
         │              │
         ▼              ▼
    FaceDetector   AudioProcessor
    (bbox+lmk)     (mel spectrogram)
         │              │
         └──────┬───────┘
                ▼
         Wav2LipONNX
         (lip-synced faces)
                │
                ▼
         VideoAssembler
         (composite + MP4)
                │
                ▼
            output.mp4

Usage::

    from stockstream.avatar import AvatarService, AvatarConfig

    svc = AvatarService(host_image="streamer.jpg")
    await svc.initialize()

    result = await svc.generate(
        task_id="demo_001",
        audio_path="tts_output.wav",
    )
    print(result.output_path)  # → data/avatar/demo_001.mp4
"""

from stockstream.avatar.models import (
    AvatarConfig,
    AvatarResult,
    AvatarStatus,
    AvatarTask,
    FaceBox,
    MelSpectrogram,
)
from stockstream.avatar.pipeline import AvatarPipeline
from stockstream.avatar.service import AvatarService

__all__ = [
    "AvatarConfig",
    "AvatarPipeline",
    "AvatarResult",
    "AvatarService",
    "AvatarStatus",
    "AvatarTask",
    "FaceBox",
    "MelSpectrogram",
]
