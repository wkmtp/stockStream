"""礼物互动引擎。"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from collections import defaultdict

from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


class GiftLevel:
    NORMAL = "normal"
    PREMIUM = "premium"
    SUPER = "super"


@dataclass
class GiftAction:
    user: str = ""
    gift_name: str = ""
    message: str = ""
    level: str = GiftLevel.NORMAL
    total_value: float = 0.0

    def to_dict(self) -> dict:
        return {
            "user": self.user, "gift_name": self.gift_name,
            "message": self.message, "level": self.level,
            "total_value": self.total_value,
        }


class GiftEngine:
    """礼物互动引擎。

    监听事件:
      live.gift_received → 礼物互动触发
    推送事件:
      live.gift_action → 感谢语+动画指令
    """

    def __init__(self, bus: EventBus | None = None) -> None:
        self._bus: EventBus | None = bus
        self.user_values: dict[str, float] = defaultdict(float)
        self.total_gifts = 0

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    async def start(self) -> None:
        bus = await self.bus

        @bus.on("live.gift_received")
        async def _on_gift(event):
            await self._handle_gift(event)

        logger.info("GiftEngine started")

    async def _handle_gift(self, event) -> None:
        data = event.data or {}
        username = data.get("username", "")
        gift_name = data.get("gift_name", "礼物")
        value = data.get("value", 0)

        self.user_values[username] += value
        self.total_gifts += 1

        total = self.user_values[username]

        if value >= 100:
            level = GiftLevel.SUPER
            msg = f"感谢{username}送来的{gift_name}！太豪气了！"
        elif value >= 10:
            level = GiftLevel.PREMIUM
            msg = f"感谢{username}送来的{gift_name}！"
        else:
            level = GiftLevel.NORMAL
            msg = f"谢谢{username}的{gift_name}！"

        action = GiftAction(
            user=username, gift_name=gift_name,
            message=msg, level=level, total_value=total,
        )

        bus = await self.bus
        await bus.emit_async("live.gift_action", action.to_dict(), source="gift")
