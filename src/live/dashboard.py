"""实时直播仪表盘。"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field

from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


@dataclass
class LiveDashboard:
    """直播数据驾驶舱。

    实时聚合所有直播指标。
    """

    current_viewers: int = 0
    total_likes: int = 0
    total_gifts: int = 0
    current_followers: int = 0
    total_comments: int = 0
    avg_stay_seconds: float = 0.0
    stock_analysis_count: int = 0
    voice_broadcast_count: int = 0
    segment_count: int = 0
    estimated_revenue: float = 0.0
    engagement_rate: float = 0.0

    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __init__(self, bus: EventBus | None = None) -> None:
        self._bus: EventBus | None = bus
        self.started_at = time.time()

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    async def start(self) -> None:
        bus = await self.bus

        @bus.on("danmu.processed")
        async def _on_danmu(event):
            self.total_comments += 1
            self.updated_at = time.time()

        @bus.on("live.like_received")
        async def _on_like(event):
            self.total_likes += 1
            self.updated_at = time.time()

        @bus.on("live.gift_received")
        async def _on_gift(event):
            self.total_gifts += 1
            data = event.data or {}
            self.estimated_revenue += data.get("value", 0)
            self.updated_at = time.time()

        @bus.on("analysis.qa_answer")
        async def _on_qa(event):
            self.stock_analysis_count += 1
            self.updated_at = time.time()

        @bus.on("tts.sentence_ready")
        async def _on_tts(event):
            self.voice_broadcast_count += 1
            self.updated_at = time.time()

        logger.info("LiveDashboard started")

    @property
    def uptime_seconds(self) -> float:
        return max(0.0, time.time() - self.started_at)

    @property
    def uptime_str(self) -> str:
        secs = self.uptime_seconds
        h, r = divmod(int(secs), 3600)
        m, s = divmod(r, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def snapshot(self) -> dict:
        return {
            "viewers": self.current_viewers,
            "likes": self.total_likes,
            "gifts": self.total_gifts,
            "followers": self.current_followers,
            "comments": self.total_comments,
            "avg_stay_seconds": round(self.avg_stay_seconds, 1),
            "stock_analysis_count": self.stock_analysis_count,
            "voice_broadcast_count": self.voice_broadcast_count,
            "segments": self.segment_count,
            "estimated_revenue": round(self.estimated_revenue, 2),
            "engagement_rate": round(self.engagement_rate, 1),
            "uptime": self.uptime_str,
        }

    def to_dict(self) -> dict:
        return self.snapshot()
