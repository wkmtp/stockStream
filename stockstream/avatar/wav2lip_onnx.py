"""Wav2Lip ONNX inference engine — lip-sync face generation.

Architecture::

    ┌─────────────────────────────────────────────────┐
    │  Wav2Lip Generator (ONNX)                       │
    │                                                 │
    │  Inputs:                                        │
    │   - face_sequences  (B, 5, 6, 96, 96)          │
    │     └─ 5 consecutive face crops, 6 ch each      │
    │        (3 RGB lower-half + 3 RGB reference)     │
    │   - mel_sequences   (B, 5, 80, 16)             │
    │     └─ 5 mel segments, 80 bins × 16 frames      │
    │                                                 │
    │  Output:                                        │
    │   - face_out  (B, 3, 96, 96)                    │
    │     └─ lip-synced face region                   │
    └─────────────────────────────────────────────────┘

Model conversion reference (PyTorch → ONNX)::

    import torch
    from models.wav2lip import Wav2Lip

    model = Wav2Lip()
    model.load_state_dict(torch.load("wav2lip_gan.pth")["state_dict"])
    model.eval()

    dummy_face = torch.randn(1, 5, 6, 96, 96)
    dummy_mel  = torch.randn(1, 5, 80, 16)

    torch.onnx.export(
        model,
        (dummy_face, dummy_mel),
        "wav2lip_gan.onnx",
        input_names=["face_sequences", "mel_sequences"],
        output_names=["face_out"],
        dynamic_axes={
            "face_sequences": {0: "batch"},
            "mel_sequences":  {0: "batch"},
            "face_out":       {0: "batch"},
        },
        opset_version=14,
    )
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

import numpy as np

from stockstream.avatar.models import AvatarConfig, MelSpectrogram

logger = logging.getLogger(__name__)

_ORT_AVAILABLE = False


def _ensure_ort() -> bool:
    global _ORT_AVAILABLE
    if _ORT_AVAILABLE:
        return True
    try:
        import onnxruntime  # noqa: F401
        _ORT_AVAILABLE = True
        return True
    except ImportError:
        return False


class Wav2LipONNX:
    """ONNX Runtime wrapper for Wav2Lip generator inference.

    Usage::

        engine = Wav2LipONNX(config)
        engine.initialize()  # loads ONNX model
        frames = engine.generate(face_crops, mel_spec)
    """

    def __init__(self, config: AvatarConfig) -> None:
        self.config = config
        self._session: "onnxruntime.InferenceSession | None" = None  # noqa: F821
        self._input_names: list[str] = []
        self._output_names: list[str] = []

    # ── lifecycle ──────────────────────────────────────────────────

    def initialize(self) -> bool:
        """Load Wav2Lip ONNX model into ONNX Runtime."""
        if not _ensure_ort():
            logger.warning("onnxruntime not installed — Wav2Lip running in placeholder mode")
            return False

        model_path = Path(self.config.wav2lip_generator_onnx)
        if not model_path.exists():
            logger.warning("Wav2Lip ONNX model not found at %s", model_path)
            return False

        try:
            import onnxruntime as ort
            # ── GPU auto-detect (Jetson CUDA / TensorRT) ──
            _available = ort.get_available_providers()
            _preferred = [
                "TensorrtExecutionProvider",   # Jetson TensorRT 8.x
                "CUDAExecutionProvider",        # CUDA 11.4
                "CPUExecutionProvider",         # 最终回退
            ]
            _providers = [p for p in _preferred if p in _available]
            if not _providers:
                _providers = ["CPUExecutionProvider"]
            logger.info("ONNX Runtime providers (available=%s, selected=%s)", _available, _providers)
            self._session = ort.InferenceSession(
                str(model_path),
                providers=_providers,
            )
            self._input_names = [inp.name for inp in self._session.get_inputs()]
            self._output_names = [out.name for out in self._session.get_outputs()]
            logger.info(
                "Wav2Lip ONNX loaded | inputs=%s outputs=%s | %s",
                self._input_names, self._output_names, model_path,
            )
            return True
        except Exception as exc:
            logger.error("Failed to load Wav2Lip ONNX: %s", exc)
            return False

    def ready(self) -> bool:
        return self._session is not None

    # ── inference ──────────────────────────────────────────────────

    def generate(
        self,
        face_crops: np.ndarray,   # (num_frames, 3, 96, 96) aligned face crops
        mel_spec: MelSpectrogram,
        progress_cb: "callable | None" = None,
    ) -> Optional[np.ndarray]:
        """Generate lip-synced face frames.

        Args:
            face_crops: Preprocessed face images (N, 3, 96, 96) float32, range ~[-1, 1] or [0, 1].
            mel_spec: Mel spectrogram from audio.
            progress_cb: Optional callback(frame_idx, total_frames) for progress.

        Returns:
            (N, 3, 96, 96) lip-synced frames, or None on failure.
        """
        if not self.ready():
            return self._placeholder_generate(face_crops)

        t0 = time.monotonic()

        num_frames = face_crops.shape[0]
        mel = mel_spec.mel  # (T_mel, 80)
        mel_step = self.config.mel_step_size  # typically 16

        # Ensure correct dtype
        face_crops = face_crops.astype(np.float32)
        mel = mel.astype(np.float32)

        results: list[np.ndarray] = []
        batch = self.config.face_batch_size

        for start in range(0, num_frames, batch):
            end = min(start + batch, num_frames)
            batch_faces, batch_mels = self._build_batch(
                face_crops, mel, start, end, num_frames, mel_step,
            )
            if batch_faces.size == 0:
                break

            feeds: dict[str, np.ndarray] = {}
            if len(self._input_names) >= 2:
                feeds[self._input_names[0]] = batch_faces
                feeds[self._input_names[1]] = batch_mels
            elif len(self._input_names) == 1:
                # Some ONNX models use a single concatenated input
                feeds[self._input_names[0]] = batch_faces
            else:
                logger.error("Unexpected number of ONNX inputs: %d", len(self._input_names))
                return None

            out = self._session.run(self._output_names, feeds)
            batch_out = out[0]  # (B, 3, 96, 96)

            for i in range(batch_out.shape[0]):
                results.append(batch_out[i])

            if progress_cb:
                progress_cb(end, num_frames)

        elapsed = time.monotonic() - t0
        fps = num_frames / elapsed if elapsed > 0 else 0
        logger.info("Wav2Lip generated %d frames in %.1fs (%.1f fps)", num_frames, elapsed, fps)

        return np.stack(results, axis=0) if results else None

    def _build_batch(
        self,
        faces: np.ndarray,
        mel: np.ndarray,
        start: int,
        end: int,
        num_frames: int,
        mel_step: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Build a batch of (face_sequences, mel_sequences) for the Wav2Lip generator.

        Wav2Lip uses 5 consecutive face frames as context.
        For a single-image input, we replicate the same face 5 times.
        """
        bs = end - start
        img_size = self.config.img_size

        # face_sequences: (B, 5, 6, 96, 96)
        # 6 channels = 3 (lower-half reference) + 3 (full reference)
        face_seq = np.zeros((bs, 5, 6, img_size, img_size), dtype=np.float32)
        for i in range(bs):
            frame_idx = start + i
            face = faces[min(frame_idx, num_frames - 1)]  # (3, 96, 96)
            # Reference face is first frame
            ref = faces[0]
            for t in range(5):
                # Lower half masked (first 3 ch) + reference full (last 3 ch)
                face_seq[i, t, :3] = face  # lower half context
                face_seq[i, t, 3:] = ref   # full reference

        # mel_sequences: (B, 5, 80, mel_step)
        T_mel = mel.shape[0]
        mel_seq = np.zeros((bs, 5, 80, mel_step), dtype=np.float32)
        for i in range(bs):
            frame_idx = start + i
            mel_idx = min(int(80.0 * frame_idx / 25.0), T_mel - mel_step - 1)
            for t in range(5):
                idx = min(mel_idx + t, T_mel - 1)
                seg = mel[idx:idx + 1] if idx + mel_step <= T_mel else mel[T_mel - mel_step:]
                # Broadcast single frame to fill mel_step
                mel_seq[i, t] = np.broadcast_to(
                    mel[min(idx, T_mel - 1)], (mel_step, 80)
                ).T  # (80, mel_step)

        return face_seq, mel_seq

    def _placeholder_generate(self, face_crops: np.ndarray) -> np.ndarray:
        """Return input frames unchanged as placeholder when ONNX model is unavailable."""
        logger.debug("Wav2Lip placeholder: returning %d frames unchanged", face_crops.shape[0])
        return face_crops.copy()
