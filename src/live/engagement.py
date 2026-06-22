"""点赞互动引擎。"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from collections import defaultdict

from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


@dataclass
class EngagementAction:
    user: str = ""
    message: str = ""
    level: str = ""  # normal / special / super / extreme
    trigger_type: str = ""

    def to_dict(self) -> dict:
        return {
            "user": self.user, "message": self.message,
            "level": self.level, "trigger_type": self.trigger_type,
        }


class EngagementEngine:
    """点赞互动引擎。

    监听事件:
      live.like_received → 点赞互动触发
    推送事件:
      live.engagement_action → 互动动作
    """

    def __init__(self, bus: EventBus | None = None) -> None:
        self._bus: EventBus | None = bus
        self.user_likes: dict[str, int] = defaultdict(int)
        self.total_likes = 0

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    async def start(self) -> None:
        bus = await self.bus

        @bus.on("live.like_received")
        async def _on_like(event):
            await self._handle_like(event)

        logger.info("EngagementEngine started")

    async def _handle_like(self, event) -> None:
        data = event.data or {}
        username = data.get("username", "")
        count = data.get("count", 1)

        self.user_likes[username] += count
        self.total_likes += count
        user_likes = self.user_likes[username]

        action = None
        if user_likes == 10 or user_likes == 20:
            action = EngagementAction(
                user=username,
                message=f"感谢{username}的点赞支持！",
                level="normal",
                trigger_type="like_10",
            )
        elif user_likes >= 100 and user_likes < 1000:
            action = EngagementAction(
                user=username,
                message=f"太给力了！感谢{username}的持续支持！",
                level="special",
                trigger_type="like_100",
            )
        elif user_likes >= 1000:
            action = EngagementAction(
                user=username,
                message=f"超级感谢{username}！你的支持是我们最大的动力！",
                level="super",
                trigger_type="like_1000",
            )

        if action:
            bus = await self.bus
            await bus.emit_async("live.engagement_action", action.to_dict(),
                                source="engagement")
