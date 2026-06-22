"""直播运营模块。

职责:
  - 直播平台接入（抖音、快手）
  - 弹幕处理中心
  - 点赞/礼物/粉丝互动
  - 运营自动化（引流、冷场处理、商业化）

依赖: core (EventBus), tts, avatar
被依赖: agents (Chief Director)
"""

from src.live.platform_gateway import LivePlatformGateway
from src.live.danmu_center import DanmuCenter
from src.live.engagement import EngagementEngine
from src.live.gift import GiftEngine
from src.live.fan_tracker import FanTracker
from src.live.operation import OperationEngine
from src.live.traffic import TrafficEngine
from src.live.anti_silence import AntiSilenceEngine
from src.live.monetization import MonetizationEngine
from src.live.clip_generator import ClipGenerator
from src.live.video_writer import VideoWriter
from src.live.dashboard import LiveDashboard

__all__ = [
    "LivePlatformGateway",
    "DanmuCenter",
    "EngagementEngine",
    "GiftEngine",
    "FanTracker",
    "OperationEngine",
    "TrafficEngine",
    "AntiSilenceEngine",
    "MonetizationEngine",
    "ClipGenerator",
    "VideoWriter",
    "LiveDashboard",
]
