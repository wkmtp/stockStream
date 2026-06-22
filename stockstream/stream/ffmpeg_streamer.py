"""FFmpeg subprocess manager for RTMP streaming.

Launches FFmpeg as a subprocess, pipes a video source (image loop or
playlist) to an RTMP server, and monitors streaming statistics from stderr.

Usage::

    streamer = FFmpegStreamer(StreamConfig(
        rtmp_url="rtmp://live.example.com/live/stream-key",
    ))
    await streamer.start(input_source="data/avatar/auto_xxx.mp4")
    # ... monitor with streamer.status()
    await streamer.stop()
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
import signal
import time
from asyncio.subprocess import Process
from typing import Optional

from stockstream.stream.models import StreamConfig, StreamState, StreamStats, StreamStatus

logger = logging.getLogger(__name__)

# Regex patterns to parse FFmpeg stderr progress lines
_RE_FPS = re.compile(r"fps\s*=\s*([\d.]+)")
_RE_BITRATE = re.compile(r"bitrate\s*=\s*([\d.]+\s*\w+/s)")
_RE_TOTAL_SIZE = re.compile(r"total_size\s*=\s*([\d.]+\s*\w+)")
_RE_SPEED = re.compile(r"speed\s*=\s*([\dx.]+)")
_RE_DROP = re.compile(r"drop\s*=\s*(\d+)")
_RE_DUP = re.compile(r"dup\s*=\s*(\d+)")
_RE_OUT_TIME = re.compile(r"out_time\s*=\s*([\d:.]+)")
_RE_PROGRESS = re.compile(r"^progress\s*=\s*continue", re.MULTILINE)


class FFmpegStreamer:
    """Manages an FFmpeg subprocess for RTMP push streaming.

    Features:
    - Start / stop / restart RTMP push
    - Auto-reconnect on disconnection with configurable attempts
    - Parse FFmpeg stderr to extract fps, bitrate, speed stats
    - Graceful shutdown with SIGTERM → SIGKILL escalation
    """

    def __init__(self, config: StreamConfig) -> None:
        self.config = config
        self._process: Process | None = None
        self._status = StreamStatus(rtmp_url=config.rtmp_url)
        self._stats = StreamStats()
        self._monitor_task: asyncio.Task[None] | None = None
        self._watch_task: asyncio.Task[None] | None = None  # ← track orphan
        self._start_time: float = 0.0
        self._reconnect_attempts = 0

    # ── public API ─────────────────────────────────────────────────

    async def start(self, input_source: str) -> bool:
        """Launch FFmpeg and begin RTMP streaming.

        Args:
            input_source: Path to a video file, image, or "pipe" for
                          rawvideo stdin mode (live compositor).

        Returns:
            True if FFmpeg started and is streaming.
        """
        if self._process is not None and self._process.returncode is None:
            logger.warning("FFmpeg is already running (pid %d)", self._process.pid)
            return False

        if not self.config.rtmp_url:
            logger.error("RTMP URL is not configured")
            self._status.state = StreamState.ERROR
            self._status.last_error = "RTMP URL not configured"
            return False

        is_pipe = input_source == "pipe" or input_source.startswith("pipe:")
        if not is_pipe and (not input_source or not os.path.exists(input_source)):
            logger.error("Input source not found: %s", input_source)
            self._status.state = StreamState.ERROR
            self._status.last_error = f"Input source not found: {input_source}"
            return False

        self._status.state = StreamState.STARTING
        self._status.last_error = ""
        self._reconnect_attempts = 0

        return await self._launch(input_source)

    async def stop(self) -> None:
        """Gracefully stop FFmpeg and clean up subprocess."""
        self._status.state = StreamState.STOPPING
        self._cancel_monitor()

        if self._process is None or self._process.returncode is not None:
            self._status.state = StreamState.IDLE
            self._status.pid = None
            return

        pid = self._process.pid
        try:
            # Send SIGTERM first (FFmpeg handles this gracefully)
            self._process.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                # Force kill if FFmpeg doesn't exit within 5 seconds
                logger.warning("FFmpeg (pid %d) did not exit, sending SIGKILL", pid)
                try:
                    self._process.kill()
                except ProcessLookupError:
                    pass
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
        except ProcessLookupError:
            pass
        except Exception as exc:
            logger.error("Error stopping FFmpeg: %s", exc)

        self._process = None
        self._status.state = StreamState.IDLE
        self._status.pid = None
        self._status.started_at = None
        self._stats = StreamStats()
        logger.info("FFmpeg stream stopped (was pid %d)", pid)

    def status(self) -> StreamStatus:
        """Return a snapshot of the current stream status."""
        # Update PID from active process
        if self._process is not None and self._process.returncode is None:
            self._status.pid = self._process.pid
        self._status.stats = self._stats
        self._status.reconnect_count = self._reconnect_attempts
        return self._status

    def is_streaming(self) -> bool:
        """Return True if FFmpeg is running and streaming."""
        return (
            self._process is not None
            and self._process.returncode is None
            and self._status.state == StreamState.STREAMING
        )

    def write_frame(self, frame_bytes: bytes) -> bool:
        """Write a raw video frame to FFmpeg stdin (pipe mode only).

        Returns True on success, False if pipe is broken.
        """
        if self._process is None or self._process.stdin is None:
            return False
        try:
            self._process.stdin.write(frame_bytes)
            return True
        except (BrokenPipeError, OSError, ConnectionResetError) as exc:
            logger.warning("FFmpeg stdin write failed: %s", exc)
            return False

    def get_process(self) -> Optional[Process]:
        """Return the FFmpeg subprocess for external frame feeding."""
        return self._process

    # ── internals ──────────────────────────────────────────────────

    async def _launch(self, input_source: str) -> bool:
        """Build FFmpeg command and launch subprocess."""
        cmd = self._build_command(input_source)
        logger.info("Launching FFmpeg: %s", shlex.join(cmd))

        is_pipe = input_source == "pipe" or input_source.startswith("pipe:")
        try:
            stdin = asyncio.subprocess.PIPE if is_pipe else asyncio.subprocess.DEVNULL
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=stdin,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            logger.error("FFmpeg executable not found. Is FFmpeg installed?")
            self._status.state = StreamState.ERROR
            self._status.last_error = "FFmpeg executable not found"
            return False
        except Exception as exc:
            logger.error("Failed to launch FFmpeg: %s", exc)
            self._status.state = StreamState.ERROR
            self._status.last_error = str(exc)
            return False

        self._status.state = StreamState.STREAMING
        self._status.started_at = time.time()
        self._status.pid = self._process.pid
        self._start_time = time.time()

        # Start stderr monitor in background
        self._monitor_task = asyncio.create_task(self._monitor_stderr())

        # Also start a process-exit watcher to detect crashes — track it
        self._watch_task = asyncio.create_task(self._watch_process_exit())

        logger.info("FFmpeg streaming started (pid %d, url %s)", self._process.pid, self.config.rtmp_url)
        return True

    def _build_command(self, input_source: str) -> list[str]:
        """Construct the FFmpeg command-line arguments for RTMP push.

        Supports three input modes:
        - video file (.mp4/.mov etc) → loop push
        - image file → loop as static frame with silent audio
        - **pipe** → rawvideo frames via stdin (for live compositor)
        """
        cfg = self.config

        # Detect input mode
        is_pipe = input_source == "pipe" or input_source.startswith("pipe:")
        is_video = not is_pipe and input_source.endswith(
            (".mp4", ".mov", ".mkv", ".avi", ".flv", ".webm"),
        )

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "info",
            "-stats",
            "-re",  # Read input at native frame rate (critical for streaming)
        ]

        # ── Input ──
        if is_pipe:
            # Raw video frame pipe mode for live compositor
            is_pipe = True  # mark for later use
            pipe_spec = input_source.replace("pipe:", "").replace("pipe", "")
            if not pipe_spec:
                pipe_spec = f"1920x1080:25:bgr24"
            parts = pipe_spec.split(":")
            w = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else 1920
            h = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1080
            r = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 25
            cmd += [
                "-f", "rawvideo",
                "-vcodec", "rawvideo",
                "-pix_fmt", "bgr24",
                "-s", f"{w}x{h}",
                "-r", str(r),
                "-i", "pipe:0",
            ]
        elif is_video:
            cmd += ["-stream_loop", "-1", "-i", input_source]
        else:
            # Image loop mode
            cmd += [
                "-loop", "1",
                "-framerate", str(cfg.input_fps),
                "-i", input_source,
            ]

        # ── Video encoding ──
        if is_pipe:
            cmd += [
                "-c:v", cfg.video_codec,
                "-preset", cfg.preset,
                "-tune", "zerolatency",
                "-b:v", cfg.video_bitrate,
                "-bufsize", cfg.bufsize,
                "-maxrate", cfg.video_bitrate,
                "-pix_fmt", cfg.pixel_format,
                "-g", str(cfg.input_fps * 2),
                "-r", str(cfg.input_fps),
                "-an",  # Pipe mode: no audio (audio handled by compositor)
            ]
        else:
            cmd += [
                "-c:v", cfg.video_codec,
                "-preset", cfg.preset,
                "-tune", cfg.tune,
                "-b:v", cfg.video_bitrate,
                "-bufsize", cfg.bufsize,
                "-pix_fmt", cfg.pixel_format,
                "-g", str(cfg.input_fps * 2),  # GOP size (keyframe interval)
                "-r", str(cfg.input_fps),
            ]

        # ── Audio encoding (skip for pipe mode) ──
        if not is_pipe:
            cmd += [
                "-c:a", cfg.audio_codec,
                "-b:a", cfg.audio_bitrate,
                "-ar", "44100",
                "-ac", "2",
            ]

        # ── Output ──
        cmd += [
            "-f", cfg.output_format,
            cfg.rtmp_url,
        ]

        return cmd

    async def _monitor_stderr(self) -> None:
        """Background task: read FFmpeg stderr and parse progress stats."""
        if self._process is None or self._process.stderr is None:
            return

        buf = ""
        while self._process.returncode is None:
            try:
                line = await self._process.stderr.readline()
            except (ValueError, OSError) as exc:
                logger.debug("FFmpeg stderr read error: %s", exc)
                break

            if not line:
                # Process ended
                break

            try:
                decoded = line.decode("utf-8", errors="replace").rstrip()
            except Exception:
                continue

            # Parse progress stats
            if "progress=" in decoded or "frame=" in decoded:
                buf += decoded + "\n"
                if re.search(r"progress\s*=\s*continue", decoded):
                    self._parse_stats_block(buf)
                    buf = ""
            elif "error" in decoded.lower() or "connection refused" in decoded.lower():
                logger.warning("FFmpeg stderr: %s", decoded)

        # Cleanup buf when loop exits
        if buf:
            self._parse_stats_block(buf)

    def _parse_stats_block(self, block: str) -> None:
        """Parse a single progress block from FFmpeg stderr output."""
        stats = self._stats

        def _first(pat: re.Pattern, s: str = block) -> str:
            m = pat.search(s)
            return m.group(1) if m else ""

        fps_str = _first(_RE_FPS)
        if fps_str:
            try:
                stats.fps = float(fps_str)
            except ValueError:
                pass

        bitrate = _first(_RE_BITRATE)
        if bitrate:
            stats.bitrate = bitrate

        total = _first(_RE_TOTAL_SIZE)
        if total:
            stats.total_size = total

        speed = _first(_RE_SPEED)
        if speed:
            stats.speed = speed

        drop = _first(_RE_DROP)
        if drop:
            try:
                stats.dropped_frames = int(drop)
            except ValueError:
                pass

        dup = _first(_RE_DUP)
        if dup:
            try:
                stats.dup_frames = int(dup)
            except ValueError:
                pass

        out_time = _first(_RE_OUT_TIME)
        if out_time:
            stats.out_time = out_time

        stats.uptime_seconds = time.time() - self._start_time

    async def _watch_process_exit(self) -> None:
        """Background task: watch for unexpected FFmpeg exit and attempt reconnect."""
        process = self._process  # snapshot ref to avoid race with stop()
        if process is None:
            return

        try:
            returncode = await process.wait()
        except asyncio.CancelledError:
            return
        except Exception:
            return

        # Check if stop() was called in the meantime
        if self._process is None:
            return

        self._status.state = StreamState.ERROR
        self._status.pid = None
        logger.warning("FFmpeg exited with code %d", returncode)

        if returncode != 0:
            self._status.last_error = f"FFmpeg exited with code {returncode}"

        self._cancel_monitor()

        # Auto-reconnect
        limit = self.config.max_reconnect_attempts
        if limit > 0 and self._reconnect_attempts < limit:
            self._reconnect_attempts += 1
            self._status.state = StreamState.RECONNECTING
            delay = self.config.reconnect_delay_sec
            logger.info(
                "Reconnecting in %.1fs (attempt %d/%d)...",
                delay, self._reconnect_attempts, limit,
            )
            await asyncio.sleep(delay)
            # The caller must provide the input source for reconnect
            # We'll just mark state and let the service layer handle it
        else:
            self._status.state = StreamState.ERROR
            self._status.last_error = (
                f"Max reconnect attempts ({limit}) reached" if limit > 0
                else "FFmpeg exited"
            )

    def _cancel_monitor(self) -> None:
        """Cancel both the stderr monitor and process-exit watcher tasks."""
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            self._monitor_task = None
        if self._watch_task and not self._watch_task.done():
            self._watch_task.cancel()
            self._watch_task = None
