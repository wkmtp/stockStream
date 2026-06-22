"""短视频自动切片。"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field

from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


@dataclass
class ClipTask:
    clip_id: str = ""
    title: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    duration: float = 0.0
    trigger: str = ""
    status: str = "pending"

    def to_dict(self) -> dict:
        return {
            "clip_id": self.clip_id, "title": self.title,
            "start_time": self.start_time, "duration": self.duration,
            "trigger": self.trigger, "status": self.status,
        }


class ClipGenerator:
    """短视频自动切片引擎。

    监听事件:
      analysis.complete       → 精彩点评切片触发
      live.gift_action        → 礼物高峰切片触发
      danmu.processed         → 高互动时段切片触发
    """

    def __init__(self, output_dir: str = "data/clips",
                 bus: EventBus | None = None) -> None:
        self.output_dir = output_dir
        self._bus: EventBus | None = bus
        self._clips: list[ClipTask] = []
        self._last_clip_time = 0.0
        self._cooldown = 60.0

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    async def start(self) -> None:
        bus = await self.bus

        @bus.on("analysis.complete")
        async def _on_analysis(event):
            data = event.data or {}
            symbol = data.get("symbol", "")
            if symbol:
                await self._create_clip(f"【{symbol}】专业分析精彩回顾",
                                       trigger="analysis")

        @bus.on("live.gift_action")
        async def _on_gift(event):
            data = event.data or {}
            if data.get("level") == "super":
                await self._create_clip("高光时刻！感谢大礼支持！",
                                       trigger="gift_peak")

        logger.info("ClipGenerator started")

    async def _create_clip(self, title: str, trigger: str,
                           duration: float = 30.0) -> ClipTask | None:
        if time.time() - self._last_clip_time < self._cooldown:
            return None

        clip = ClipTask(
            clip_id=f"clip_{int(time.time())}",
            title=title,
            start_time=time.time(),
            duration=duration,
            trigger=trigger,
            status="created",
        )
        self._clips.append(clip)
        self._last_clip_time = time.time()

        bus = await self.bus
        await bus.emit_async("live.clip_created", clip.to_dict(), source="clip_gen")
        return clip

    def manual_clip(self, start_time: float, end_time: float,
                    title: str = "") -> ClipTask:
        clip = ClipTask(
            clip_id=f"manual_{int(time.time())}",
            title=title or "手动切片",
            start_time=start_time,
            end_time=end_time,
            duration=end_time - start_time,
            trigger="manual",
            status="created",
        )
        self._clips.append(clip)
        return clip

    def get_stats(self) -> dict:
        return {
            "total_clips": len(self._clips),
            "output_dir": self.output_dir,
        }
