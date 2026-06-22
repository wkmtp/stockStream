"""Live compositor — real-time video compositing pipeline for digital human streaming.

Redesigns the streaming data flow:

    BEFORE:  Avatar MP4 → FFmpeg loop → RTMP  (static content)

    AFTER:   Avatar frames ──┐
             Market data ────┤
             TTS subtitles ──┼──► LiveCompositor → raw frames → FFmpeg pipe → RTMP
             Chart renderer──┘

Supports two modes:
1. **Pre-render mode**: modify VideoAssembler to overlay before MP4 encoding
   (for non-realtime, high-quality VOD)
2. **Live pipe mode**: generate avatar MP4 → decode frames → overlay → pipe to FFmpeg
   (for real-time RTMP push)

The live pipe mode reads the generated MP4 in a background thread, overlays
info on each frame, and feeds them through FFmpeg's stdin as rawvideo.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from stockstream.video.layout_engine import LayoutEngine, LayoutConfig, OverlayData
from stockstream.video.scene_manager import SceneManager, SceneType

logger = logging.getLogger(__name__)


@dataclass
class CompositorConfig:
    """Live compositor configuration."""

    # Input
    avatar_mp4_path: str = ""

    # Output
    output_mode: str = "pipe"  # "pipe" to FFmpeg, "file" to MP4
    output_path: str = ""

    # RTMP (for pipe mode)
    rtmp_url: str = ""
    video_bitrate: str = "4000k"
    audio_bitrate: str = "128k"
    fps: int = 25
    preset: str = "veryfast"

    # Frame dimensions
    width: int = 1920
    height: int = 1080

    # Update intervals
    chart_refresh_sec: float = 3.0      # Re-render chart every N seconds
    data_refresh_sec: float = 1.0       # Refresh price data every N seconds

    # Whether to stop after input video ends
    loop: bool = True

    # FFmpeg path
    ffmpeg_path: str = "ffmpeg"


@dataclass
class CompositorState:
    """Live compositor runtime state."""

    running: bool = False
    current_symbol: str = ""
    current_name: str = ""
    current_price: float = 0.0
    current_change_pct: float = 0.0
    current_subtitle: str = ""
    subtitle_visible: bool = False
    subtitle_updated_at: float = 0.0
    frame_count: int = 0
    fps_actual: float = 0.0
    error: str = ""


class LiveCompositor:
    """Live video compositing pipeline.

    Usage::

        compositor = LiveCompositor(config)
        compositor.update_market_data(symbol="600519", kline=rows, fund=rows, ...)
        compositor.update_subtitle("贵州茅台今日上涨2.5%")
        await compositor.composite_and_push(avatar_mp4="data/avatar/auto_xxx.mp4")
        # ... frames are being composited and pushed to RTMP ...
        await compositor.stop()
    """

    def __init__(
        self,
        config: CompositorConfig | None = None,
        layout_config: LayoutConfig | None = None,
        scene_manager: SceneManager | None = None,
    ) -> None:
        self.cfg = config or CompositorConfig()
        self.layout = LayoutEngine(config=layout_config or LayoutConfig())
        self.state = CompositorState()
        self._process: Optional[subprocess.Popen] = None
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

        # Smart scene engine (shared reference)
        self.scene_manager = scene_manager

        # Cached data
        self._kline_data: list[dict] = []
        self._fund_data: list[dict] = []

        # Chart cache: avoid re-rendering every frame
        self._cached_chart_rgba: Optional[np.ndarray] = None
        self._last_chart_render: float = 0.0

    # ── data update API ────────────────────────────────────────────

    def update_market_data(
        self,
        symbol: str,
        name: str = "",
        price: float = 0.0,
        change_pct: float = 0.0,
        kline_data: list[dict] | None = None,
        fund_data: list[dict] | None = None,
    ) -> None:
        """Update cached market data for compositing."""
        self.state.current_symbol = symbol
        if name:
            self.state.current_name = name
        self.state.current_price = price
        self.state.current_change_pct = change_pct
        if kline_data is not None:
            self._kline_data = kline_data
        if fund_data is not None:
            self._fund_data = fund_data
        # Invalidate chart cache
        self._cached_chart_rgba = None

    def update_subtitle(self, text: str, visible: bool = True) -> None:
        """Update the current subtitle text."""
        self.state.current_subtitle = text
        self.state.subtitle_visible = visible
        self.state.subtitle_updated_at = time.monotonic()

    # ── main pipeline ──────────────────────────────────────────────

    async def composite_and_push(self, avatar_mp4: str) -> None:
        """Start compositing the avatar MP4 with live overlays and push to RTMP.

        This reads the generated MP4 frame-by-frame, applies the layout
        engine overlay, and pipes the result to FFmpeg for RTMP push.
        """
        self.cfg.avatar_mp4_path = avatar_mp4
        self._stop_event.clear()
        self.state.running = True
        self._task = asyncio.create_task(self._pipeline_loop())

    async def stop(self) -> None:
        """Stop the compositor and clean up resources."""
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._kill_ffmpeg()
        self.state.running = False
        self.state.frame_count = 0

    def is_running(self) -> bool:
        return self.state.running

    # ── internal pipeline ──────────────────────────────────────────

    async def _pipeline_loop(self) -> None:
        """Main compositing loop: read MP4 → overlay → pipe to FFmpeg."""
        import cv2

        mp4_path = self.cfg.avatar_mp4_path
        if not mp4_path or not os.path.exists(mp4_path):
            self.state.error = f"Avatar MP4 not found: {mp4_path}"
            logger.error(self.state.error)
            self.state.running = False
            return

        # Start FFmpeg subprocess for RTMP push via pipe
        if not self._start_ffmpeg_pipe():
            self.state.error = "Failed to start FFmpeg pipe"
            self.state.running = False
            return

        # Open video file
        cap = cv2.VideoCapture(mp4_path)
        if not cap.isOpened():
            self.state.error = f"Cannot open video: {mp4_path}"
            logger.error(self.state.error)
            self._kill_ffmpeg()
            self.state.running = False
            return

        vid_fps = cap.get(cv2.CAP_PROP_FPS) or self.cfg.fps
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        frame_interval = 1.0 / vid_fps

        logger.info("LiveCompositor: reading %s @ %.1f fps → RTMP %s",
                     mp4_path, vid_fps, self.cfg.rtmp_url)

        self.state.frame_count = 0
        start_time = time.monotonic()
        last_chart_update = 0.0

        try:
            while not self._stop_event.is_set():
                ret, frame = cap.read()
                if not ret:
                    if self.cfg.loop:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    else:
                        break

                # Build overlay data from current state
                overlay = OverlayData(
                    symbol=self.state.current_symbol,
                    name=self.state.current_name,
                    price_now=self.state.current_price,
                    change_pct=self.state.current_change_pct,
                    kline_data=self._kline_data,
                    fund_data=self._fund_data,
                    subtitle_text=self.state.current_subtitle,
                    subtitle_visible=self.state.subtitle_visible,
                    face_frame=frame,  # avatar frame becomes the face overlay
                )

                # ── Scene mode: render current scene ──
                if self.layout.cfg.scene_mode and self.scene_manager is not None:
                    scene_rgba = self.scene_manager.render_current_scene(
                        width_px=self.layout.cfg.chart_area_width,
                        height_px=self.layout.cfg.effective_main_height,
                        force_refresh=(self.state.frame_count % 25 == 0),  # refresh every 1s
                    )
                    overlay.scene_rgba = scene_rgba
                    overlay.scene_label = self.scene_manager.scene_label

                # Compose the full layout frame
                composited = await asyncio.to_thread(self.layout.compose, overlay)

                # Resize to target dimensions if needed
                if composited.shape[1] != self.cfg.width or composited.shape[0] != self.cfg.height:
                    composited = cv2.resize(composited, (self.cfg.width, self.cfg.height))

                # Write to FFmpeg stdin pipe
                self._write_frame(composited)

                self.state.frame_count += 1

                # Frame pacing
                elapsed = time.monotonic() - start_time
                expected = self.state.frame_count * frame_interval
                sleep_time = expected - elapsed
                if sleep_time > 0:
                    await asyncio.sleep(min(sleep_time, 0.1))
                else:
                    await asyncio.sleep(0.001)  # yield to event loop

                # Update FPS stats periodically
                if self.state.frame_count % (int(vid_fps) * 2) == 0:
                    self.state.fps_actual = self.state.frame_count / max(elapsed, 0.001)

        except asyncio.CancelledError:
            logger.info("LiveCompositor cancelled")
        except Exception as exc:
            logger.exception("LiveCompositor pipeline error: %s", exc)
            self.state.error = str(exc)
        finally:
            # 24h: 检查 cap 是否存在再 release，防止摄像头初始化失败导致二次异常
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    logger.debug("LiveCompositor: cap.release() failed")
            self._kill_ffmpeg()
            logger.info("LiveCompositor stopped (frames=%d)", self.state.frame_count)

    # ── FFmpeg pipe management ─────────────────────────────────────

    def _start_ffmpeg_pipe(self) -> bool:
        """Launch FFmpeg subprocess that reads rawvideo from stdin and pushes to RTMP."""
        ffmpeg = shutil.which(self.cfg.ffmpeg_path)
        if not ffmpeg:
            ffmpeg = self.cfg.ffmpeg_path

        cmd = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "warning",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-pix_fmt", "bgr24",
            "-s", f"{self.cfg.width}x{self.cfg.height}",
            "-r", str(self.cfg.fps),
            "-i", "pipe:0",           # Read raw frames from stdin
            "-c:v", "libx264",
            "-preset", self.cfg.preset,
            "-tune", "zerolatency",
            "-b:v", self.cfg.video_bitrate,
            "-maxrate", self.cfg.video_bitrate,
            "-bufsize", str(int(self.cfg.video_bitrate.replace("k", "")) * 2) + "k",
            "-pix_fmt", "yuv420p",
            "-g", str(self.cfg.fps * 2),
            "-r", str(self.cfg.fps),
            "-an",                     # No audio in pipe mode (audio from avatar MP4 is lost)
            "-f", "flv",
            self.cfg.rtmp_url,
        ]

        try:
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            # 24h 稳定性：后台线程消费 stderr，防止管道缓冲区满导致 FFmpeg 卡死
            import threading
            threading.Thread(
                target=self._drain_stderr,
                daemon=True,
                name="ffmpeg-stderr",
            ).start()
            logger.info("FFmpeg pipe started → %s", self.cfg.rtmp_url)
            return True
        except FileNotFoundError:
            logger.error("FFmpeg not found at: %s", ffmpeg)
            return False
        except Exception as exc:
            logger.error("Failed to start FFmpeg pipe: %s", exc)
            return False

    def _write_frame(self, frame: np.ndarray) -> None:
        """Write a single BGR frame to FFmpeg stdin."""
        if self._process is None or self._process.stdin is None:
            return
        try:
            self._process.stdin.write(frame.tobytes())
        except (BrokenPipeError, OSError) as exc:
            logger.warning("FFmpeg pipe write failed: %s", exc)
            # 24h: 写入失败时必须清理子进程，防止孤儿进程
            self._kill_ffmpeg()

    def _kill_ffmpeg(self) -> None:
        """Kill the FFmpeg subprocess."""
        if self._process is None:
            return
        try:
            self._process.stdin.close()
        except Exception:
            logger.debug("FFmpeg stdin close failed during kill")
        try:
            self._process.terminate()
            self._process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self._process.kill()
        except Exception:
            pass
        self._process = None

    def _drain_stderr(self) -> None:
        """Background thread: read and discard FFmpeg stderr to prevent pipe buffer deadlock."""
        if self._process is None or self._process.stderr is None:
            return
        try:
            for _ in self._process.stderr:
                pass
        except Exception:
            logger.debug("FFmpeg stderr drain exception during compositor cleanup")


# ── pre-render compositor (for VOD / non-realtime) ──────────────────────

class PreRenderCompositor:
    """Overlay charts/subtitles onto avatar frames BEFORE MP4 encoding.

    This modifies the VideoAssembler frame compositing step to include
    layout layers. Produces a combined MP4 with audio preserved.

    Usage::

        prc = PreRenderCompositor(layout_engine)
        composited_frames = prc.overlay_on_frames(face_frames, overlay_data)
        # Pass composited_frames to VideoAssembler instead of face_frames
    """

    def __init__(self, layout_engine: LayoutEngine | None = None) -> None:
        self.layout = layout_engine or LayoutEngine()

    def overlay_on_frames(
        self,
        avatar_bg: np.ndarray,         # Background image BGR (H, W, 3)
        face_frames: np.ndarray,       # Wav2Lip output (N, 3, 96, 96) float32
        face_box,                      # FaceBox with position info
        overlay_data: OverlayData,
        config: LayoutConfig | None = None,
    ) -> np.ndarray:
        """Generate composited frames with full layout overlay.

        Returns composited BGR uint8 frames (N, H, W, 3) at layout resolution.
        """
        import cv2

        cfg = config or LayoutConfig()
        num_frames = face_frames.shape[0]

        # Step 1: composite face onto avatar background
        # This replicates VideoAssembler._composite_frames logic
        bg = avatar_bg.copy()
        img_size = 96
        expand_scale = 1.5
        expanded = face_box.expand(expand_scale)

        bx = max(0, expanded.x)
        by = max(0, expanded.y)
        bw = min(expanded.width, bg.shape[1] - bx)
        bh = min(expanded.height, bg.shape[0] - by)

        output_frames = np.zeros((num_frames, cfg.height, cfg.width, 3), dtype=np.uint8)

        for i in range(num_frames):
            # Composite face onto background
            frame = bg.copy()
            face = face_frames[i].transpose(1, 2, 0)
            f_min, f_max = face.min(), face.max()
            if f_min < 0:
                face = (face + 1.0) / 2.0
            face = np.clip(face * 255.0, 0, 255).astype(np.uint8)
            face = cv2.cvtColor(face, cv2.COLOR_RGB2BGR)
            face_resized = cv2.resize(face, (bw, bh))

            # Soft mask blending
            mask = self._soft_rect_mask(bw, bh, feather=5)
            mask_3ch = np.stack([mask] * 3, axis=-1)
            roi = frame[by:by + bh, bx:bx + bw]
            blended = (face_resized * mask_3ch + roi * (1.0 - mask_3ch)).astype(np.uint8)
            frame[by:by + bh, bx:bx + bw] = blended

            # Step 2: apply layout engine with face frame
            od = OverlayData(
                symbol=overlay_data.symbol,
                name=overlay_data.name,
                price_now=overlay_data.price_now,
                change_pct=overlay_data.change_pct,
                kline_data=overlay_data.kline_data,
                fund_data=overlay_data.fund_data,
                subtitle_text=overlay_data.subtitle_text,
                subtitle_visible=overlay_data.subtitle_visible,
                face_frame=frame,
            )
            composited = self.layout.compose(od)
            output_frames[i] = cv2.resize(composited, (cfg.width, cfg.height))

        return output_frames

    @staticmethod
    def _soft_rect_mask(w: int, h: int, feather: int = 5) -> np.ndarray:
        yy = np.linspace(0, 1, h)
        xx = np.linspace(0, 1, w)
        mask_y = np.minimum(
            yy / (feather / h) if feather > 0 else np.full(h, 1e9),
            (1 - yy) / (feather / h) if feather > 0 else np.full(h, 1e9),
        )
        mask_x = np.minimum(
            xx / (feather / w) if feather > 0 else np.full(w, 1e9),
            (1 - xx) / (feather / w) if feather > 0 else np.full(w, 1e9),
        )
        mask = np.outer(np.clip(mask_y, 0, 1), np.clip(mask_x, 0, 1))
        return mask.astype(np.float32)
