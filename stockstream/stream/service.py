"""In-memory stream bus + FFmpeg RTMP streaming service.

Provides:
- Pub/sub event bus: ticks, selections, agent events, danmu
- RTMP push streaming: start/stop/monitor via FFmpeg subprocess

Usage::

    svc = StreamService()
    # Pub/sub
    await svc.publish({"type": "market.tick", ...})
    event = await svc.next_event()

    # RTMP streaming
    await svc.start_streaming(input_source="data/avatar/output.mp4")
    status = svc.get_stream_status()
    await svc.stop_streaming()
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from stockstream.core.config import get_settings
from stockstream.stream.ffmpeg_streamer import FFmpegStreamer
from stockstream.stream.models import StreamConfig, StreamState, StreamStatus

logger = logging.getLogger(__name__)


class StreamService:
    """Small pub/sub bus for ticks, selections, agent events, and danmu.
    
    Extended with FFmpeg-based RTMP push streaming capability.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=settings.stream_queue_size)

        # ── RTMP streaming ─────────────────────────────────────
        rtmp_url = getattr(settings, "stream_rtmp_url", "")
        self._stream_config = StreamConfig(rtmp_url=rtmp_url)
        self._ffmpeg = FFmpegStreamer(self._stream_config)
        # Last used input source for reconnect
        self._last_input_source: str = ""

    # ── pub/sub (unchanged) ─────────────────────────────────────

    async def publish(self, event: dict) -> None:
        """Publish an event, dropping the oldest event when the queue is full."""

        if self.queue.full():
            _ = self.queue.get_nowait()
        await self.queue.put(event)

    async def next_event(self) -> dict:
        """Wait for and return the next event."""

        return await self.queue.get()

    # ── RTMP streaming ──────────────────────────────────────────

    async def start_streaming(self, input_source: str = "") -> dict:
        """Start RTMP push streaming via FFmpeg.

        Args:
            input_source: Path to video file or image to stream.
                          Defaults to last-used source if empty.

        Returns:
            Status dict with state and details.
        """
        source = input_source or self._last_input_source
        if not source:
            return {"error": "No input source provided", "state": StreamState.IDLE.value}

        self._last_input_source = source
        ok = await self._ffmpeg.start(source)

        if not ok:
            status = self._ffmpeg.status()
            return status.to_dict()

        # Publish stream-started event on the internal bus
        await self.publish({
            "type": "stream.started",
            "rtmp_url": self._stream_config.rtmp_url,
            "input_source": source,
        })

        return self._ffmpeg.status().to_dict()

    async def stop_streaming(self) -> dict:
        """Stop the active RTMP stream.

        Returns:
            Status dict after stopping.
        """
        await self._ffmpeg.stop()

        # Publish stream-stopped event
        await self.publish({
            "type": "stream.stopped",
            "rtmp_url": self._stream_config.rtmp_url,
        })

        return self._ffmpeg.status().to_dict()

    def get_stream_status(self) -> dict:
        """Return the current RTMP stream status snapshot.

        Includes: state, rtmp_url, pid, uptime, fps, bitrate, dropped frames.
        """
        return self._ffmpeg.status().to_dict()

    def is_streaming(self) -> bool:
        """Return True if RTMP stream is active."""
        return self._ffmpeg.is_streaming()

    def write_frame(self, frame_bytes: bytes) -> bool:
        """Write a raw video frame to FFmpeg stdin (pipe mode only)."""
        return self._ffmpeg.write_frame(frame_bytes)

    def get_ffmpeg_process(self):
        """Return the FFmpeg subprocess for external frame feeding."""
        return self._ffmpeg.get_process()

    @property
    def rtmp_url(self) -> str:
        """The configured RTMP push URL."""
        return self._stream_config.rtmp_url
