"""短视频文案生成。"""
from __future__ import annotations
import logging
import random
from dataclasses import dataclass, field

from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


@dataclass
class VideoCopywriting:
    title: str = ""
    cover_text: str = ""
    tags: list[str] = field(default_factory=list)
    description: str = ""
    clip_id: str = ""

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "cover_text": self.cover_text,
            "tags": self.tags,
            "description": self.description,
            "clip_id": self.clip_id,
        }


class VideoWriter:
    """短视频文案生成引擎。

    根据切片内容生成财经爆款风格标题+封面+标签+简介。
    """

    _TITLE_TEMPLATES = [
        "【必看】{stock_name}后市走势深度解析！",
        "震惊！{stock_name}竟走出这种形态...",
        "职业交易员曝光：{stock_name}的三大关键信号",
        "一分钟看懂{stock_name}接下来怎么走",
        "高手都在关注的{stock_name}关键点位",
    ]

    _TAGS = [
        "股票", "财经", "投资", "A股", "技术分析",
        "炒股", "短线", "实盘", "理财", "财富自由",
    ]

    def __init__(self, bus: EventBus | None = None) -> None:
        self._bus: EventBus | None = bus
        self._history: list[VideoCopywriting] = []

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    async def start(self) -> None:
        bus = await self.bus

        @bus.on("live.clip_created")
        async def _on_clip(event):
            data = event.data or {}
            await self.generate(clip_id=data.get("clip_id", ""),
                              trigger=data.get("trigger", ""))

        logger.info("VideoWriter started")

    async def generate(self, clip_id: str, trigger: str = "",
                       stock_name: str = "") -> VideoCopywriting:
        title_tpl = random.choice(self._TITLE_TEMPLATES)
        name = stock_name or "热门股票"

        copy = VideoCopywriting(
            clip_id=clip_id,
            title=title_tpl.format(stock_name=name),
            cover_text=f"深度解析{name}",
            tags=random.sample(self._TAGS, min(5, len(self._TAGS))),
            description=f"本期视频深度分析{name}的走势，分享投资思路与操作策略。#{name} #股票分析 #财经",
        )
        self._history.append(copy)

        bus = await self.bus
        await bus.emit_async("live.copywriting_ready", copy.to_dict(),
                            source="video_writer")
        return copy

    def get_stats(self) -> dict:
        return {"generated_count": len(self._history)}
