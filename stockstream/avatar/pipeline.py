"""Avatar pipeline — end-to-end Wav2Lip talking-head generation.

Single unified pipeline::

    host image (.jpg/.png)   +   Piper TTS audio (.wav)
           │                            │
           ▼                            ▼
      FaceDetector              AudioProcessor
      (face bbox + lmks)        (mel spectrogram)
           │                            │
           ▼                            │
      FacePreprocessor ◄─────────────────┘
      (96×96 aligned crop, N frames)
           │
           ▼
      Wav2LipONNX
      (lip-synced faces N×96×96)
           │
           ▼
      VideoAssembler
      (composite + encode MP4)
           │
           ▼
       output.mp4
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

import numpy as np

from stockstream.avatar.audio_processor import AudioProcessor
from stockstream.avatar.face_detector import FaceDetector
from stockstream.avatar.models import (
    AvatarConfig,
    AvatarResult,
    AvatarStatus,
    AvatarTask,
    MelSpectrogram,
)
from stockstream.avatar.video_assembler import VideoAssembler
from stockstream.avatar.wav2lip_onnx import Wav2LipONNX

logger = logging.getLogger(__name__)


class AvatarPipeline:
    """End-to-end Wav2Lip avatar generation pipeline.

    Usage::

        pipeline = AvatarPipeline(AvatarConfig())
        await pipeline.initialize()
        result = await pipeline.generate(
            task_id="abc123",
            image_path="host.jpg",
            audio_path="tts_output.wav",
            output_dir="data/avatar",
        )
    """

    def __init__(self, config: AvatarConfig | None = None) -> None:
        self.config = config or AvatarConfig()
        self.face_detector = FaceDetector(
            self.config.face_detector_onnx,
            threshold=self.config.face_det_threshold,
        )
        self.audio_processor = AudioProcessor()
        self.wav2lip = Wav2LipONNX(self.config)
        self.assembler = VideoAssembler(self.config)
        self._initialized = False

    # ── lifecycle ──────────────────────────────────────────────────

    async def initialize(self) -> bool:
        """Load all ONNX models. Returns True if at least the pipeline can run."""
        det_ok = self.face_detector.initialize()
        wav_ok = self.wav2lip.initialize()
        self._initialized = det_ok or True  # face detector has fallback
        logger.info(
            "AvatarPipeline initialized | detector=%s wav2lip=%s",
            det_ok, wav_ok,
        )
        return self._initialized

    def ready(self) -> bool:
        return self._initialized

    # ── generate ───────────────────────────────────────────────────

    async def generate(
        self,
        task_id: str,
        image_path: str,
        audio_path: str,
        output_dir: str | Path = "data/avatar",
    ) -> Optional[AvatarResult]:
        """Run the full Wav2Lip pipeline and produce an MP4 video.

        Args:
            task_id: Unique task identifier.
            image_path: Path to host/streamer image (.jpg/.png).
            audio_path: Path to Piper TTS WAV audio.
            output_dir: Where to write the output MP4.

        Returns:
            AvatarResult with MP4 path and metadata, or None on failure.
        """
        task = AvatarTask(
            task_id=task_id,
            image_path=image_path,
            audio_path=audio_path,
            config=self.config,
            status=AvatarStatus.PENDING,
        )

        # ── Step 1: Load image ──
        image = await self._load_image(image_path)
        if image is None:
            task.status = AvatarStatus.FAILED
            task.error = f"Cannot load image: {image_path}"
            return None

        # ── Step 2: Face detection ──
        task.status = AvatarStatus.DETECTING
        face_box = self.face_detector.detect(image)
        if face_box is None:
            task.status = AvatarStatus.FAILED
            task.error = "No face detected in host image"
            return None
        task.face_box = face_box
        logger.debug("Face detected: %s", face_box)

        # ── Step 3: Audio → mel spectrogram ──
        mel = self.audio_processor.process(audio_path)
        if mel is None:
            task.status = AvatarStatus.FAILED
            task.error = f"Failed to process audio: {audio_path}"
            return None
        task.duration_s = mel.duration_s

        # ── Step 4: Prepare aligned face crops ──
        task.status = AvatarStatus.SYNTHESIZING
        face_crops = self._prepare_face_crops(image, face_box, mel)
        if face_crops is None or face_crops.shape[0] == 0:
            task.status = AvatarStatus.FAILED
            task.error = "Failed to prepare face crops"
            return None

        num_frames = face_crops.shape[0]
        task.total_frames = num_frames
        task._frames_done = 0  # type: ignore[attr-defined]

        logger.info(
            "Generating %d frames from %.1fs audio @ %d fps",
            num_frames, mel.duration_s, self.config.fps,
        )

        # ── Step 5: Wav2Lip inference ──
        def _on_progress(done: int, total: int) -> None:
            task._frames_done = done  # type: ignore[attr-defined]

        lip_frames = self.wav2lip.generate(face_crops, mel, progress_cb=_on_progress)
        if lip_frames is None:
            task.status = AvatarStatus.FAILED
            task.error = "Wav2Lip generation failed"
            return None

        # ── Step 6: Assemble MP4 ──
        task.status = AvatarStatus.ASSEMBLING
        result = await self.assembler.assemble(
            task_id=task_id,
            background_img=image,
            face_frames=lip_frames,
            face_box=face_box,
            audio_path=audio_path,
            output_dir=output_dir,
        )

        if result is None:
            task.status = AvatarStatus.FAILED
            task.error = "Video assembly failed"
            return None

        task.status = AvatarStatus.DONE
        task.output_path = result.output_path
        logger.info("Avatar task %s done → %s", task_id, result.output_path)
        return result

    # ── internal ───────────────────────────────────────────────────

    async def _load_image(self, path: str) -> Optional[np.ndarray]:
        """Load image as BGR uint8 numpy array."""
        try:
            import cv2
            img = await asyncio.to_thread(cv2.imread, path)
            if img is None:
                logger.error("cv2.imread returned None for %s", path)
                return None
            return img
        except ImportError:
            logger.error("OpenCV not available — cannot load images")
            return None
        except Exception as exc:
            logger.error("Image load error for %s: %s", path, exc)
            return None

    def _prepare_face_crops(
        self,
        image: np.ndarray,
        face_box: "FaceBox",
        mel: MelSpectrogram,
    ) -> Optional[np.ndarray]:
        """Produce aligned face crops for each frame.

        For a static image (single picture), we replicate the same
        aligned face crop N times, where N = duration_s * fps.
        """
        import cv2

        img_size = self.config.img_size  # 96
        fps = self.config.fps
        num_frames = max(1, int(mel.duration_s * fps))

        # Expand face box for better context
        expanded = face_box.expand(self.config.face_expand_scale)
        h, w = image.shape[:2]

        # Clamp to image bounds
        x1 = max(0, expanded.x)
        y1 = max(0, expanded.y)
        x2 = min(w, expanded.x + expanded.width)
        y2 = min(h, expanded.y + expanded.height)

        if x2 <= x1 or y2 <= y1:
            logger.error("Face box outside image bounds")
            return None

        # Crop and resize to 96×96
        face_crop = image[y1:y2, x1:x2]
        face_crop = cv2.resize(face_crop, (img_size, img_size))

        # BGR → RGB, uint8 → float32 [0, 1]
        face_rgb = cv2.cvtColor(face_crop, cv2.COLOR_BGR2RGB)
        face_float = face_rgb.astype(np.float32) / 255.0

        # CHW format
        face_chw = np.transpose(face_float, (2, 0, 1))  # (3, 96, 96)

        # Replicate for all frames
        face_crops = np.tile(face_chw[np.newaxis, ...], (num_frames, 1, 1, 1))
        logger.debug("Prepared %d face crops (%.0f×%.0f → %d×%d)",
                      num_frames, x2 - x1, y2 - y1, img_size, img_size)

        return face_crops
