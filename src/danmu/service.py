"""弹幕服务。"""
from __future__ import annotations
import logging
from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


class DanmuService:
    """弹幕服务 — 弹幕模拟生成和发布。

    推送事件:
      danmu.new  — 新弹幕到达
    """

    def __init__(self, bus: EventBus | None = None) -> None:
        self._bus: EventBus | None = bus

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    async def push_danmu(self, platform: str, username: str,
                         content: str, level: int = 0) -> None:
        """推送一条弹幕。"""
        bus = await self.bus
        await bus.emit_async("danmu.new", {
            "platform": platform,
            "username": username,
            "content": content,
            "user_level": level,
        }, source="danmu")
