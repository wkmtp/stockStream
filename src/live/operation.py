"""运营AI — 互动监控与自动话题切换。"""
from __future__ import annotations
import logging
import time
from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


class OperationEngine:
    """运营AI引擎。

    监控指标：
      - 弹幕量趋势
      - 在线人数趋势
      - 点赞量趋势
      - 礼物量趋势

    行为：
      - 互动下降 → 自动切换话题
      - 推送新的热点股票/财经趣闻
    """

    def __init__(self, bus: EventBus | None = None) -> None:
        self._bus: EventBus | None = bus
        self._metrics_history: list[dict] = []
        self._total_interactions = 0
        self._last_interaction_time = time.time()

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    async def start(self) -> None:
        bus = await self.bus

        @bus.on("danmu.processed")
        async def _on_danmu(event):
            self._total_interactions += 1
            self._last_interaction_time = time.time()

        @bus.on("live.like_received")
        async def _on_like(event):
            self._total_interactions += 1
            self._last_interaction_time = time.time()

        logger.info("OperationEngine started")

    async def evaluate_engagement(self) -> dict:
        """评估互动质量。"""
        inactive_seconds = time.time() - self._last_interaction_time

        if inactive_seconds > 120:
            return {
                "status": "low",
                "suggestion": "切换热门话题",
                "inactive_seconds": inactive_seconds,
            }
        elif inactive_seconds > 60:
            return {
                "status": "declining",
                "suggestion": "增加互动引导",
                "inactive_seconds": inactive_seconds,
            }
        return {
            "status": "active",
            "inactive_seconds": inactive_seconds,
        }

    def get_stats(self) -> dict:
        return {
            "total_interactions": self._total_interactions,
            "inactive_seconds": round(time.time() - self._last_interaction_time, 1),
        }
