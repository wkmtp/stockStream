"""冷场处理引擎。"""
from __future__ import annotations
import logging
import random
import time
from dataclasses import dataclass

from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


@dataclass
class AntiSilenceAction:
    action_type: str = ""
    message: str = ""
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "action_type": self.action_type,
            "message": self.message,
            "timestamp": self.timestamp,
        }


class AntiSilenceEngine:
    """冷场处理引擎。

    如果 N 秒无互动，自动生成内容填补空白。
    """

    _QUESTIONS = [
        "最近茅台走势很稳，大家怎么看？",
        "有没有朋友关注新能源板块的？",
        "今天的市场情绪怎么样？大家聊聊",
        "消费股最近是不是有机会？",
        "大盘在这个位置，大家是看多还是看空？",
    ]

    _TOPICS = [
        "来看一下最近资金流向，北向资金今天流入明显...",
        "分享一个短线操作的思路，供大家参考...",
        "聊聊今天盘面的几个关键信号...",
    ]

    def __init__(self, silence_threshold: int = 30,
                 bus: EventBus | None = None) -> None:
        self.silence_threshold = silence_threshold
        self._last_interaction = 0.0  # 0 = 已处于"冷场"状态
        self._bus: EventBus | None = bus

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    async def start(self) -> None:
        bus = await self.bus

        @bus.on("danmu.processed")
        async def _on_danmu(event):
            self._last_interaction = time.time()

        @bus.on("live.like_received")
        async def _on_like(event):
            self._last_interaction = time.time()

        logger.info("AntiSilenceEngine started (threshold=%ds)", self.silence_threshold)

    def silence_duration(self) -> float:
        if self._last_interaction == 0:
            return 999.0
        return time.time() - self._last_interaction

    def is_silent(self) -> bool:
        return self.silence_duration() >= self.silence_threshold

    def get_action(self) -> AntiSilenceAction | None:
        if not self.is_silent():
            return None
        if random.random() < 0.5:
            msg = random.choice(self._QUESTIONS)
            return AntiSilenceAction("ask_question", msg, time.time())
        else:
            msg = random.choice(self._TOPICS)
            return AntiSilenceAction("switch_topic", msg, time.time())

    def get_stats(self) -> dict:
        return {
            "silence_threshold": self.silence_threshold,
            "current_silence_seconds": round(self.silence_duration(), 1),
            "is_silent": self.is_silent(),
        }
