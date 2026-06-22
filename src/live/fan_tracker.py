"""粉丝增长追踪。"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from collections import defaultdict

from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


@dataclass
class FanSnapshot:
    platform: str = ""
    follower_count: int = 0
    new_followers: int = 0
    unfollow_count: int = 0
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "follower_count": self.follower_count,
            "new_followers": self.new_followers,
            "timestamp": self.timestamp,
        }


@dataclass
class DailyReport:
    platform: str = ""
    date: str = ""
    total_growth: int = 0
    peak_count: int = 0
    hourly_data: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "date": self.date,
            "total_growth": self.total_growth,
            "peak_count": self.peak_count,
            "hourly_data": self.hourly_data,
        }


class FanTracker:
    """粉丝增长追踪。

    监听事件:
      live.follower_change → 粉丝数变更
    推送事件:
      live.fan_snapshot → 定期快照
    """

    def __init__(self, bus: EventBus | None = None) -> None:
        self._bus: EventBus | None = bus
        self._data: dict[str, list[FanSnapshot]] = defaultdict(list)
        self._current: dict[str, FanSnapshot] = {}

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    async def start(self) -> None:
        bus = await self.bus

        @bus.on("live.follower_change")
        async def _on_follower(event):
            await self._record(event)

        logger.info("FanTracker started")

    async def _record(self, event) -> None:
        data = event.data or {}
        platform = data.get("platform", "")
        count = data.get("follower_count", 0)

        snap = FanSnapshot(
            platform=platform,
            follower_count=count,
            timestamp=time.time(),
        )
        self._current[platform] = snap
        self._data[platform].append(snap)

    def get_current(self, platform: str) -> FanSnapshot | None:
        return self._current.get(platform)

    def get_trend(self, platform: str, limit: int = 60) -> list[dict]:
        return [s.to_dict() for s in self._data.get(platform, [])[-limit:]]

    def generate_daily_report(self, platform: str) -> DailyReport:
        snaps = self._data.get(platform, [])
        if not snaps:
            return DailyReport(platform=platform)

        return DailyReport(
            platform=platform,
            total_growth=snaps[-1].follower_count - snaps[0].follower_count if len(snaps) > 1 else 0,
            peak_count=max(s.follower_count for s in snaps),
        )
