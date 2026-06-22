"""数字人渲染服务。"""
from __future__ import annotations
import logging
from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


class AvatarService:
    """数字人渲染服务。

    监听事件:
      tts.sentence_ready → 驱动嘴型动画
    推送事件:
      avatar.frame_ready  — 渲染帧就绪
    """

    def __init__(self, host_image: str = "", output_dir: str = "data/avatar",
                 bus: EventBus | None = None) -> None:
        self.host_image = host_image
        self.output_dir = output_dir
        self._bus: EventBus | None = bus
        self._initialized = False

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    async def initialize(self) -> None:
        self._initialized = True
        logger.info("AvatarService initialized")

    async def start(self) -> None:
        if not self._initialized:
            await self.initialize()
        logger.info("AvatarService started")

    async def stop(self) -> None:
        logger.info("AvatarService stopped")
