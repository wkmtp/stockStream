"""Live platform gateway — unified abstraction for all live-streaming platforms.

Supports:
- 抖音 (Douyin)
- 快手 (Kuaishou)
- Future: B站 (Bilibili), 视频号 (WeChat Channels)

Architecture::

    LivePlatformGateway (unified interface)
    ├── DouyinConnector
    ├── KuaishouConnector
    └── [future connectors]

Usage::

    from stockstream.platform_gateway import LivePlatformGateway
    gw = LivePlatformGateway()
    gw.register("douyin", DouyinConnector(config))
    events = await gw.start_all()
"""

from stockstream.platform_gateway.common.interface import LivePlatformGateway
from stockstream.platform_gateway.common.models import (
    Platform,
    LiveEvent,
    LiveEventType,
    CommentEvent,
    LikeEvent,
    GiftEvent,
    FollowEvent,
    ViewerEvent,
    PlatformConfig,
)
from stockstream.platform_gateway.douyin.connector import DouyinConnector
from stockstream.platform_gateway.kuaishou.connector import KuaishouConnector

__version__ = "1.0.0"
__all__ = [
    "LivePlatformGateway",
    "Platform",
    "LiveEvent", "LiveEventType",
    "CommentEvent", "LikeEvent", "GiftEvent", "FollowEvent", "ViewerEvent",
    "PlatformConfig",
    "DouyinConnector",
    "KuaishouConnector",
]
