"""ONNX face detector — locate face bounding box + landmarks in host image.

Supports multiple ONNX face detection backends:
- SCRFD (InsightFace) — lightweight, fast
- RetinaFace — more accurate, common in Wav2Lip pipelines
- Placeholder — graceful fallback when no model is available
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np

from stockstream.avatar.models import FaceBox, AvatarConfig

logger = logging.getLogger(__name__)

# Lazy imports for optional deps
_ORT_AVAILABLE = False
_CV2_AVAILABLE = False


def _ensure_deps() -> tuple:
    """Check optional ONNX Runtime / OpenCV availability."""
    global _ORT_AVAILABLE, _CV2_AVAILABLE
    try:
        import onnxruntime as _ort  # noqa: F401
        _ORT_AVAILABLE = True
    except ImportError:
        _ORT_AVAILABLE = False
    try:
        import cv2 as _cv2  # noqa: F401
        _CV2_AVAILABLE = True
    except ImportError:
        _CV2_AVAILABLE = False
    return _ORT_AVAILABLE, _CV2_AVAILABLE


class FaceDetector:
    """ONNX-based face detection for Wav2Lip preprocessing.

    Input:  BGR image (H, W, 3) as numpy array, any resolution.
    Output: FaceBox with bbox coordinates and 5-point landmarks.

    Usage::

        det = FaceDetector("models/face_detector.onnx")
        box = det.detect(image)
    """

    # SCRFD model: input 640x640, output bboxes + landmarks + kps
    INPUT_SIZE = (640, 640)

    def __init__(self, model_path: str, threshold: float = 0.5) -> None:
        self.model_path = Path(model_path)
        self.threshold = threshold
        self._session: "onnxruntime.InferenceSession | None" = None  # noqa: F821

    # ── lifecycle ──────────────────────────────────────────────────

    def initialize(self) -> bool:
        """Load ONNX model into memory. Returns True on success."""
        _ensure_deps()
        if not _ORT_AVAILABLE:
            logger.warning("onnxruntime not installed — face detector running in placeholder mode")
            return False
        if not self.model_path.exists():
            logger.warning("Face detector ONNX not found at %s", self.model_path)
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
            logger.info("FaceDetector ONNX providers (available=%s, selected=%s)", _available, _providers)
            self._session = ort.InferenceSession(
                str(self.model_path),
                providers=_providers,
            )
            logger.info("Face detector loaded: %s", self.model_path)
            return True
        except Exception as exc:
            logger.error("Failed to load face detector ONNX: %s", exc)
            return False

    def ready(self) -> bool:
        return self._session is not None

    # ── detection ──────────────────────────────────────────────────

    def detect(self, image: np.ndarray) -> Optional[FaceBox]:
        """Detect the primary face in the image.

        Args:
            image: BGR uint8 numpy array (H, W, 3).

        Returns:
            FaceBox or None if no face found above threshold.
        """
        if not self.ready():
            return self._fallback_detect(image)

        import cv2
        h, w = image.shape[:2]

        # Preprocess: resize to 640x640, normalize to [0, 1]
        input_img = cv2.resize(image, self.INPUT_SIZE)
        input_img = input_img.astype(np.float32)
        # SCRFD-style: mean subtraction (127.5, 127.5, 127.5), scale 1/128
        blob = (input_img - 127.5) / 128.0
        blob = np.transpose(blob, (2, 0, 1))  # HWC → CHW
        blob = np.expand_dims(blob, axis=0)     # add batch dim → (1, 3, 640, 640)

        outputs = self._session.run(None, {self._session.get_inputs()[0].name: blob})

        boxes = self._parse_outputs(outputs, w, h)
        if not boxes:
            return None
        return boxes[0]

    def _parse_outputs(
        self, outputs: list[np.ndarray], orig_w: int, orig_h: int,
    ) -> list[FaceBox]:
        """Parse SCRFD-style ONNX outputs into FaceBox list."""
        # SCRFD typically outputs: scores (N,), bboxes (N, 4), kps (N, 10) or (N, 5, 2)
        # Output indices may vary by model version — handle common layouts
        scores, bboxes, landmarks = None, None, None

        for out in outputs:
            arr = np.squeeze(out)
            if arr.ndim == 1 and arr.dtype in (np.float32, np.float16):
                if scores is None:
                    scores = arr
            elif arr.ndim == 2 and arr.shape[-1] == 4 and (scores is not None or bboxes is None):
                if bboxes is None:
                    bboxes = arr
            elif arr.ndim == 2 and arr.shape[-1] == 10:
                landmarks = arr
            elif arr.ndim == 3 and arr.shape[-1] == 2 and arr.shape[-2] == 5:
                landmarks = arr.reshape(-1, 10)

        if bboxes is None or scores is None:
            return []

        scale_x = orig_w / self.INPUT_SIZE[0]
        scale_y = orig_h / self.INPUT_SIZE[1]

        results: list[FaceBox] = []
        for i, score in enumerate(scores):
            score_f = float(score)
            if score_f < self.threshold:
                continue
            x1, y1, x2, y2 = bboxes[i] * [scale_x, scale_y, scale_x, scale_y]
            box = FaceBox(
                x=int(x1),
                y=int(y1),
                width=int(x2 - x1),
                height=int(y2 - y1),
                confidence=score_f,
            )
            if landmarks is not None and i < landmarks.shape[0]:
                lm = landmarks[i]
                box.landmarks = [
                    (float(lm[j] * scale_x), float(lm[j + 1] * scale_y))
                    for j in range(0, 10, 2)
                ]
            results.append(box)

        # Sort by confidence descending
        results.sort(key=lambda b: b.confidence, reverse=True)
        return results

    def _fallback_detect(self, image: np.ndarray) -> Optional[FaceBox]:
        """OpenCV Haar-cascade fallback when ONNX model is unavailable."""
        _ensure_deps()
        import cv2
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(60, 60))
        if len(faces) == 0:
            return None
        x, y, w, h = faces[0]
        return FaceBox(x=int(x), y=int(y), width=int(w), height=int(h), confidence=1.0)
