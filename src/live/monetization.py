"""商业化运营引擎。"""
from __future__ import annotations
import logging
import random
import time
from dataclasses import dataclass
from enum import Enum

from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


class MonetizeType(Enum):
    MEMBER = "member"
    COURSE = "course"
    COMMUNITY = "community"
    AD = "ad"


@dataclass
class MonetizeAction:
    mtype: MonetizeType = MonetizeType.MEMBER
    message: str = ""
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "type": self.mtype.value,
            "message": self.message,
            "timestamp": self.timestamp,
        }


class MonetizationEngine:
    """商业化运营引擎。

    每 N 分钟触发商业化动作（会员/课程/社群/广告）。
    """

    _TEMPLATES = {
        MonetizeType.MEMBER: [
            "加入会员专享每日深度研报，让投资更专业！",
            "成为会员解锁更多投资策略分享！",
        ],
        MonetizeType.COURSE: [
            "想系统学习技术分析？关注主页了解详情！",
            "完整的K线战法教程已上线，点击主页查看！",
        ],
        MonetizeType.COMMUNITY: [
            "想加入交流群的朋友，看主页联系方式！",
            "欢迎加入我们的投资社群，一起交流学习！",
        ],
        MonetizeType.AD: [
            "感谢金主爸爸的支持！",
        ],
    }

    def __init__(self, interval_minutes: int = 30,
                 bus: EventBus | None = None) -> None:
        self.interval_seconds = interval_minutes * 60
        self._last_action_time = time.time()
        self._bus: EventBus | None = bus
        self._history: list[MonetizeAction] = []
        self._rotation = list(MonetizeType)

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    async def start(self) -> None:
        logger.info("MonetizationEngine started (interval=%ds)", self.interval_seconds)

    async def should_trigger(self) -> bool:
        return time.time() - self._last_action_time >= self.interval_seconds

    async def trigger(self, mtype: MonetizeType | None = None) -> MonetizeAction:
        if mtype is None:
            idx = len(self._history) % len(self._rotation)
            mtype = self._rotation[idx]

        templates = self._TEMPLATES.get(mtype, [""])
        msg = random.choice(templates)
        self._last_action_time = time.time()

        action = MonetizeAction(mtype=mtype, message=msg, timestamp=time.time())
        self._history.append(action)

        bus = await self.bus
        await bus.emit_async("live.monetize_action", action.to_dict(), source="monetization")
        return action

    async def force_trigger(self, mtype: MonetizeType | None = None) -> MonetizeAction:
        return await self.trigger(mtype)

    def get_stats(self) -> dict:
        return {
            "interval_minutes": self.interval_seconds // 60,
            "history_count": len(self._history),
            "seconds_since_last": round(time.time() - self._last_action_time, 1),
        }
