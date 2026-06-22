"""Data models for RTMP streaming with FFmpeg."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class StreamState(str, Enum):
    """RTMP stream lifecycle state."""

    IDLE = "idle"
    STARTING = "starting"
    STREAMING = "streaming"
    STOPPING = "stopping"
    ERROR = "error"
    RECONNECTING = "reconnecting"


@dataclass(slots=True)
class StreamConfig:
    """FFmpeg RTMP streaming configuration.

    Attributes:
        rtmp_url: RTMP push URL, e.g. rtmp://live.example.com/live/stream-key
        input_format: Input source type: 'image2' (single image loop), 'concat' (playlist), 'pipe'
        input_fps: Input frame rate for loop or pipe sources
        video_codec: FFmpeg encoder (h264_nvenc for NVIDIA, libx264 for CPU)
        audio_codec: FFmpeg audio encoder (aac)
        video_bitrate: Target video bitrate, e.g. '2500k'
        audio_bitrate: Target audio bitrate, e.g. '128k'
        preset: Encoder preset (ultrafast → placebo)
        tune: Encoder tuning (zerolatency recommended for live)
        pixel_format: Output pixel format
        output_format: Container format (flv for RTMP)
        bufsize: Encoder buffer size
        max_reconnect_attempts: Max auto-reconnect attempts
        reconnect_delay_sec: Seconds between reconnection attempts
        monitor_interval_sec: How often to parse FFmpeg stats from stderr
    """

    rtmp_url: str = ""
    input_format: str = "image2"
    input_fps: int = 25
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    video_bitrate: str = "2500k"
    audio_bitrate: str = "128k"
    preset: str = "veryfast"
    tune: str = "zerolatency"
    pixel_format: str = "yuv420p"
    output_format: str = "flv"
    bufsize: str = "5000k"
    max_reconnect_attempts: int = 5
    reconnect_delay_sec: float = 3.0
    monitor_interval_sec: float = 2.0


@dataclass
class StreamStats:
    """Parsed FFmpeg streaming statistics.

    Captured from FFmpeg stderr progress lines.
    """

    fps: float = 0.0
    bitrate: str = "0k"
    total_size: str = "0kB"
    speed: str = "0x"
    dropped_frames: int = 0
    dup_frames: int = 0
    out_time: str = "00:00:00.00"
    uptime_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "fps": round(self.fps, 1),
            "bitrate": self.bitrate,
            "total_size": self.total_size,
            "speed": self.speed,
            "dropped_frames": self.dropped_frames,
            "dup_frames": self.dup_frames,
            "out_time": self.out_time,
            "uptime_seconds": round(self.uptime_seconds, 1),
        }


@dataclass
class StreamStatus:
    """Full RTMP stream status snapshot."""

    state: StreamState = StreamState.IDLE
    rtmp_url: str = ""
    pid: Optional[int] = None
    started_at: Optional[float] = None
    reconnect_count: int = 0
    last_error: str = ""
    stats: StreamStats = field(default_factory=StreamStats)

    def to_dict(self) -> dict:
        return {
            "state": self.state.value,
            "rtmp_url": self.rtmp_url,
            "pid": self.pid,
            "started_at": self.started_at,
            "reconnect_count": self.reconnect_count,
            "last_error": self.last_error,
            "stats": self.stats.to_dict(),
        }
