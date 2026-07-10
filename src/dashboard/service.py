"""数据驾驶舱服务。"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


@dataclass
class DashboardData:
    viewers: int = 0
    likes: int = 0
    gifts: int = 0
    followers: int = 0
    comments: int = 0
    revenue: float = 0.0
    segments: int = 0
    started_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "viewers": self.viewers, "likes": self.likes,
            "gifts": self.gifts, "followers": self.followers,
            "comments": self.comments, "revenue": self.revenue,
            "segments": self.segments,
            "uptime_seconds": round(time.time() - self.started_at, 1),
        }


class DashboardService:
    """数据驾驶舱 — 聚合所有直播数据。

    监听事件:
      danmu.new            → 弹幕计数
      live.gift_received   → 礼物计数
      live.like_received   → 点赞计数
      live.follower_change → 粉丝计数
    """

    def __init__(self, bus: EventBus | None = None) -> None:
        self._bus: EventBus | None = bus
        self.data = DashboardData(started_at=time.time())

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    async def start(self) -> None:
        bus = await self.bus

        @bus.on("danmu.new")
        async def _on_danmu(event):
            self.data.comments += 1

        @bus.on("live.gift_received")
        async def _on_gift(event):
            self.data.gifts += 1
            if event.data and isinstance(event.data, dict):
                self.data.revenue += event.data.get("value", 0)

        @bus.on("live.like_received")
        async def _on_like(event):
            self.data.likes += 1

        logger.info("DashboardService started")

    def snapshot(self) -> dict:
        return self.data.to_dict()
