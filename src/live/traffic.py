"""自动引流引擎。"""
from __future__ import annotations
import logging
import random
import time
from dataclasses import dataclass

from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


@dataclass
class TrafficAction:
    message: str = ""
    action_type: str = "cta"
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "message": self.message,
            "action_type": self.action_type,
            "timestamp": self.timestamp,
        }


class TrafficEngine:
    """自动引流引擎。

    每 N 分钟自动生成关注引导话术。
    """

    _TEMPLATES = [
        "喜欢这种分析方式的朋友，点个关注不迷路！",
        "每天实时解盘，关注主播不错过每一波行情！",
        "觉得有帮助的老铁，双击屏幕点个关注！",
        "关注主播，第一时间获取市场热点解析！",
        "新来的朋友，点关注加入我们的投资交流圈！",
        "每天下午3点准时复盘，关注锁定直播间！",
        "免费分享投资思路，点关注支持一下！",
    ]

    def __init__(self, interval_minutes: int = 15,
                 bus: EventBus | None = None) -> None:
        self.interval_seconds = interval_minutes * 60
        self._last_action_time = time.time()
        self._bus: EventBus | None = bus
        self._used: list[int] = []

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    async def start(self) -> None:
        logger.info("TrafficEngine started (interval=%ds)", self.interval_seconds)

    async def should_trigger(self) -> bool:
        return time.time() - self._last_action_time >= self.interval_seconds

    async def trigger(self) -> TrafficAction:
        """生成引流话术。"""
        available = [i for i in range(len(self._TEMPLATES)) if i not in self._used]
        if not available:
            self._used = []
            available = list(range(len(self._TEMPLATES)))
        idx = random.choice(available)
        self._used.append(idx)
        self._last_action_time = time.time()

        action = TrafficAction(
            message=self._TEMPLATES[idx],
            action_type="follow_cta",
            timestamp=time.time(),
        )

        bus = await self.bus
        await bus.emit_async("live.traffic_action", action.to_dict(), source="traffic")
        return action

    async def force_trigger(self) -> TrafficAction:
        self._used = []
        return await self.trigger()

    def get_stats(self) -> dict:
        return {
            "interval_minutes": self.interval_seconds // 60,
            "seconds_since_last": round(time.time() - self._last_action_time, 1),
            "templates_total": len(self._TEMPLATES),
            "templates_used": len(self._used),
        }
