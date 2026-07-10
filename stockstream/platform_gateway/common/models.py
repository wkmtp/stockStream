"""Common data models for the live platform gateway."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── Platform ─────────────────────────────────────────────────────

class Platform(str, Enum):
    """Supported live-streaming platforms."""
    DOUYIN = "douyin"
    KUAISHOU = "kuaishou"
    BILIBILI = "bilibili"
    WECHAT_CHANNELS = "wechat_channels"


# ── Live Event Types ─────────────────────────────────────────────

class LiveEventType(str, Enum):
    """Unified live event types across all platforms."""
    COMMENT = "comment"
    LIKE = "like"
    GIFT = "gift"
    FOLLOW = "follow"
    UNFOLLOW = "unfollow"
    VIEWER_COUNT = "viewer_count"
    SHARE = "share"
    ENTER_ROOM = "enter_room"
    ROOM_STATS = "room_stats"
    PLATFORM_ERROR = "platform_error"
    PLATFORM_CONNECTED = "platform_connected"
    PLATFORM_DISCONNECTED = "platform_disconnected"


# ── Gift Levels ──────────────────────────────────────────────────

class GiftLevel(str, Enum):
    NORMAL = "normal"        # 普通礼物 (< 10 元)
    PREMIUM = "premium"      # 高级礼物 (10-100 元)
    SUPER = "super"          # 超级礼物 (> 100 元)


# ── Events ───────────────────────────────────────────────────────

@dataclass()
class BaseEvent:
    """Base class for all live events."""
    platform: Platform
    event_type: LiveEventType
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = field(default_factory=time.time)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass()
class CommentEvent(BaseEvent):
    """A viewer comment/chat message."""
    event_type: LiveEventType = LiveEventType.COMMENT
    user_id: str = ""
    username: str = ""
    content: str = ""
    user_level: int = 0
    is_fan: bool = False

    def to_dict(self) -> dict:
        return {
            "platform": self.platform.value,
            "type": "comment",
            "user": self.username,
            "user_id": self.user_id,
            "level": self.user_level,
            "content": self.content,
            "is_fan": self.is_fan,
            "timestamp": self.timestamp,
            "event_id": self.event_id,
        }


@dataclass()
class LikeEvent(BaseEvent):
    """A like event."""
    event_type: LiveEventType = LiveEventType.LIKE
    user_id: str = ""
    username: str = ""
    count: int = 1
    total_likes: int = 0

    def to_dict(self) -> dict:
        return {
            "platform": self.platform.value,
            "type": "like",
            "user": self.username,
            "user_id": self.user_id,
            "count": self.count,
            "total_likes": self.total_likes,
            "timestamp": self.timestamp,
            "event_id": self.event_id,
        }


@dataclass()
class GiftEvent(BaseEvent):
    """A gift/donation event."""
    event_type: LiveEventType = LiveEventType.GIFT
    user_id: str = ""
    username: str = ""
    gift_name: str = ""
    gift_count: int = 1
    gift_value: float = 0.0        # 价值 (元)
    gift_level: GiftLevel = GiftLevel.NORMAL
    total_value: float = 0.0       # 累计礼物价值

    def to_dict(self) -> dict:
        return {
            "platform": self.platform.value,
            "type": "gift",
            "user": self.username,
            "user_id": self.user_id,
            "gift_name": self.gift_name,
            "gift_count": self.gift_count,
            "gift_value": self.gift_value,
            "gift_level": self.gift_level.value,
            "total_value": self.total_value,
            "timestamp": self.timestamp,
            "event_id": self.event_id,
        }


@dataclass()
class FollowEvent(BaseEvent):
    """A follow/unfollow event."""
    event_type: LiveEventType = LiveEventType.FOLLOW
    user_id: str = ""
    username: str = ""
    follower_count: int = 0

    def to_dict(self) -> dict:
        return {
            "platform": self.platform.value,
            "type": self.event_type.value,
            "user": self.username,
            "user_id": self.user_id,
            "follower_count": self.follower_count,
            "timestamp": self.timestamp,
            "event_id": self.event_id,
        }


@dataclass()
class ViewerEvent(BaseEvent):
    """Viewer count update."""
    event_type: LiveEventType = LiveEventType.VIEWER_COUNT
    viewer_count: int = 0
    peak_count: int = 0

    def to_dict(self) -> dict:
        return {
            "platform": self.platform.value,
            "type": "viewer_count",
            "viewer_count": self.viewer_count,
            "peak_count": self.peak_count,
            "timestamp": self.timestamp,
            "event_id": self.event_id,
        }


# ── Unified LiveEvent (union) ────────────────────────────────────

LiveEvent = CommentEvent | LikeEvent | GiftEvent | FollowEvent | ViewerEvent


# ── Platform Config ──────────────────────────────────────────────

@dataclass
class PlatformConfig:
    """Configuration for a single platform connector."""
    platform: Platform
    cookie: str = ""
    room_id: str = ""
    rtmp_url: str = ""
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    reconnect_interval: float = 5.0       # seconds between reconnect attempts
    max_reconnect_attempts: int = 10
    heartbeat_interval: float = 30.0      # seconds
    enabled: bool = True

    @classmethod
    def from_env_douyin(cls) -> PlatformConfig:
        """Load Douyin config from environment variables."""
        import os
        return cls(
            platform=Platform.DOUYIN,
            cookie=os.getenv("DOUYIN_COOKIE", ""),
            room_id=os.getenv("DOUYIN_ROOM_ID", ""),
            rtmp_url=os.getenv("DOUYIN_RTMP_URL", ""),
        )

    @classmethod
    def from_env_kuaishou(cls) -> PlatformConfig:
        """Load Kuaishou config from environment variables."""
        import os
        return cls(
            platform=Platform.KUAISHOU,
            cookie=os.getenv("KUAISHOU_COOKIE", ""),
            room_id=os.getenv("KUAISHOU_ROOM_ID", ""),
            rtmp_url=os.getenv("KUAISHOU_RTMP_URL", ""),
        )
