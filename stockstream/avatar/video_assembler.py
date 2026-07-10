"""Video assembler — lip-synced face frames + background + audio → MP4.

Supports two backends:
- FFmpeg (subprocess) — preferred, produces H.264 MP4
- imageio / OpenCV — fallback, writes AVI then converts
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np

from stockstream.avatar.models import AvatarConfig, AvatarResult, FaceBox

logger = logging.getLogger(__name__)


class VideoAssembler:
    """Composite lip-synced face back onto the original image and encode MP4.

    Pipeline::

        original image (BG)
            + lip-synced face frames (96×96, placed at face bbox)
            = composite frames
            + audio (WAV)
            = MP4 (H.264 + AAC)
    """

    def __init__(self, config: AvatarConfig) -> None:
        self.config = config

    # ── main API ───────────────────────────────────────────────────

    async def assemble(
        self,
        task_id: str,
        background_img: np.ndarray,        # (H, W, 3) BGR uint8, original image
        face_frames: np.ndarray,           # (N, 3, 96, 96) float32, lip-synced faces
        face_box: FaceBox,                 # where to paste the face
        audio_path: str,                   # original Piper WAV
        output_dir: str | Path,
        *,
        overlay_frames: Optional[np.ndarray] = None,  # (N, H_out, W_out, 3) BGR pre-composited
        overlay_width: int = 0,
        overlay_height: int = 0,
    ) -> Optional[AvatarResult]:
        """Assemble the final MP4 video.

        Args:
            task_id: Avatar task identifier.
            background_img: Original host image BGR uint8 (H, W, 3).
            face_frames: Lip-synced faces (N, 3, 96, 96) float32, channel values vary by model.
            face_box: Where to paste the face region.
            audio_path: Path to the input WAV file.
            output_dir: Directory for output MP4.
            overlay_frames: Optional pre-composited frames with charts/subtitles.
                            When provided, used directly instead of face-compositing.
            overlay_width: Width of overlay frames.
            overlay_height: Height of overlay frames.

        Returns:
            AvatarResult with output path, or None on failure.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{task_id}.mp4"

        num_frames = face_frames.shape[0]
        bg_h, bg_w = background_img.shape[:2]

        # Determine output resolution
        if overlay_frames is not None and overlay_width > 0 and overlay_height > 0:
            out_w, out_h = overlay_width, overlay_height
        else:
            out_w, out_h = bg_w, bg_h

        # Step 1: Composite face back onto background → frame images
        frame_dir = output_dir / f"{task_id}_frames"
        frame_dir.mkdir(exist_ok=True)

        await asyncio.to_thread(
            self._composite_frames,
            background_img, face_frames, face_box, frame_dir,
            overlay_frames=overlay_frames,
        )

        # Step 2: Encode frames + audio → MP4 via FFmpeg
        duration_s = num_frames / self.config.output_fps
        success = await self._encode_mp4(
            frame_dir, audio_path, output_path,
            fps=self.config.output_fps,
            crf=self.config.output_crf,
        )

        # Cleanup frames
        shutil.rmtree(frame_dir, ignore_errors=True)

        if not success or not output_path.exists():
            return None

        file_size = output_path.stat().st_size

        return AvatarResult(
            task_id=task_id,
            output_path=str(output_path.resolve()),
            duration_s=duration_s,
            total_frames=num_frames,
            width=out_w,
            height=out_h,
            file_size_bytes=file_size,
        )

    # ── frame compositing ──────────────────────────────────────────

    def _composite_frames(
        self,
        bg: np.ndarray,           # (H, W, 3) BGR uint8
        faces: np.ndarray,        # (N, 3, 96, 96) float32
        face_box: FaceBox,
        out_dir: Path,
        overlay_frames: Optional[np.ndarray] = None,  # pre-composited frames
    ) -> None:
        """Paste lip-synced faces onto the background image and save as PNG frames.

        If overlay_frames is provided, those pre-composited frames are saved
        directly instead of doing face-compositing on-the-fly. This enables
        the real-time layout engine (charts + subtitles) to be baked into the MP4.
        """
        import cv2

        # ── fast path: pre-composited overlay frames ──
        if overlay_frames is not None:
            num = min(faces.shape[0], overlay_frames.shape[0])
            for i in range(num):
                cv2.imwrite(str(out_dir / f"frame_{i:06d}.png"), overlay_frames[i])
            logger.debug("Wrote %d pre-composited overlay frames to %s", num, out_dir)
            return

        # ── normal path: face compositing ──
        img_size = self.config.img_size  # 96
        expand_scale = self.config.face_expand_scale  # 1.5
        expanded = face_box.expand(expand_scale)

        # Ensure expanded box is within image bounds
        bx = max(0, expanded.x)
        by = max(0, expanded.y)
        bw = min(expanded.width, bg.shape[1] - bx)
        bh = min(expanded.height, bg.shape[0] - by)

        for i in range(faces.shape[0]):
            frame = bg.copy()

            # Get the lip-synced face (CHW → HWC, float32 → uint8)
            face = faces[i].transpose(1, 2, 0)  # (96, 96, 3)

            # Normalize: Wav2Lip output is typically in [-1, 1] or [0, 1]
            f_min, f_max = face.min(), face.max()
            if f_min < 0:
                face = (face + 1.0) / 2.0  # [-1, 1] → [0, 1]
            face = np.clip(face * 255.0, 0, 255).astype(np.uint8)

            # Convert RGB → BGR for OpenCV
            face = cv2.cvtColor(face, cv2.COLOR_RGB2BGR)

            # Resize face to fit the expanded face box region
            face_resized = cv2.resize(face, (bw, bh))

            # Paste with smooth blending at edges
            # Use a soft mask: full opacity in center, fade at edges
            mask = self._soft_rect_mask(bw, bh, feather=5)
            mask_3ch = np.stack([mask] * 3, axis=-1)

            roi = frame[by:by + bh, bx:bx + bw]
            blended = (face_resized * mask_3ch + roi * (1.0 - mask_3ch)).astype(np.uint8)
            frame[by:by + bh, bx:bx + bw] = blended

            # Write frame
            cv2.imwrite(str(out_dir / f"frame_{i:06d}.png"), frame)

        logger.debug("Wrote %d composite frames to %s", faces.shape[0], out_dir)

    @staticmethod
    def _soft_rect_mask(w: int, h: int, feather: int = 5) -> np.ndarray:
        """Create a soft rectangular mask (1.0 inside, fading to 0 at edges)."""
        yy = np.linspace(0, 1, h)
        xx = np.linspace(0, 1, w)
        mask_y = np.minimum(yy / (feather / h) if feather > 0 else yy * 1e9,
                            (1 - yy) / (feather / h) if feather > 0 else (1 - yy) * 1e9)
        mask_x = np.minimum(xx / (feather / w) if feather > 0 else xx * 1e9,
                            (1 - xx) / (feather / w) if feather > 0 else (1 - xx) * 1e9)
        mask = np.outer(np.clip(mask_y, 0, 1), np.clip(mask_x, 0, 1))
        return mask.astype(np.float32)

    # ── video encoding ─────────────────────────────────────────────

    async def _encode_mp4(
        self,
        frame_dir: Path,
        audio_path: str,
        output_path: Path,
        fps: int = 25,
        crf: int = 23,
    ) -> bool:
        """Encode PNG frames + WAV audio → MP4 via FFmpeg subprocess."""
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            logger.error("FFmpeg not found in PATH — cannot encode MP4")
            return False

        cmd = [
            ffmpeg, "-y",
            "-framerate", str(fps),
            "-i", str(frame_dir / "frame_%06d.png"),
            "-i", str(audio_path),
            "-c:v", self.config.output_codec,
            "-pix_fmt", self.config.output_pix_fmt,
            "-crf", str(crf),
            "-c:a", "aac",
            "-b:a", "128k",
            "-shortest",
            "-movflags", "+faststart",
            str(output_path),
        ]

        logger.debug("FFmpeg encode: %s", " ".join(cmd))
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=120.0,
            )
            if proc.returncode != 0:
                err_text = stderr.decode("utf-8", errors="replace")
                logger.error("FFmpeg encoding failed (rc=%d): %s", proc.returncode, err_text[:500])
                return False
            logger.info("MP4 encoded: %s (%.1f MB)", output_path.name,
                        output_path.stat().st_size / (1024 * 1024))
            return True
        except Exception as exc:
            logger.error("FFmpeg subprocess error: %s", exc)
            return False
