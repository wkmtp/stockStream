"""Clip generator — auto-generate short video clips from live content.

Real-time analysis of live content to identify:
- Hot stock moments
- High interaction periods
- Gift peaks
- Memorable commentary

Generates:
- 30-second clips
- 60-second clips
- 90-second clips
Auto-saves to disk.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ClipTrigger(str, Enum):
    HOT_STOCK = "hot_stock"           # 热点股票飙升
    HIGH_INTERACTION = "high_interaction"  # 高互动时段
    GIFT_PEAK = "gift_peak"          # 礼物高峰
    MEMORABLE = "memorable"          # 精彩点评
    MARKET_EVENT = "market_event"    # 市场重大事件
    MANUAL = "manual"               # 手动触发


class ClipLength(str, Enum):
    SHORT_30 = "30s"
    MEDIUM_60 = "60s"
    LONG_90 = "90s"


@dataclass(slots=True)
class ClipTask:
    """A clip generation task."""
    clip_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    trigger: ClipTrigger = ClipTrigger.MANUAL
    clip_length: ClipLength = ClipLength.SHORT_30
    start_time: float = 0.0        # relative to stream start
    end_time: float = 0.0
    title: str = ""
    description: str = ""
    source_type: str = ""           # "script" | "audio" | "video"
    segment_id: str = ""
    output_path: str = ""
    status: str = "pending"         # pending | generating | done | failed
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "clip_id": self.clip_id,
            "trigger": self.trigger.value,
            "clip_length": self.clip_length.value,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "title": self.title,
            "description": self.description,
            "source_type": self.source_type,
            "segment_id": self.segment_id,
            "output_path": self.output_path,
            "status": self.status,
        }


class ClipGenerator:
    """Auto clip generation from live stream analysis.

    Monitors the live stream for clip-worthy moments and
    generates short video clips automatically.

    Usage::

        gen = ClipGenerator(output_dir="data/clips")
        clip = gen.evaluate_moment(script_data, interaction_data)
        if clip:
            await gen.generate_clip(clip)
    """

    def __init__(self, output_dir: str = "data/clips") -> None:
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self._clip_history: list[ClipTask] = []
        self._clip_history_max: int = 500  # 24h: 防止无界增长
        self._total_clips = 0
        self._last_clip_time: float = 0.0
        self._cooldown_seconds: float = 120.0     # min 2 min between auto-clips
        # Interaction tracking for hot moment detection
        self._recent_danmu_count: int = 0
        self._recent_like_count: int = 0
        self._recent_gift_value: float = 0.0
        self._last_sample_time: float = time.time()

    def evaluate_moment(
        self,
        segment_data: dict | None = None,
        danmu_count: int = 0,
        like_count: int = 0,
        gift_value: float = 0.0,
        stock_change_pct: float = 0.0,
    ) -> ClipTask | None:
        """Evaluate if the current moment is clip-worthy.

        Returns a ClipTask if worthy, None otherwise.
        """
        now = time.time()

        # Cooldown check
        if now - self._last_clip_time < self._cooldown_seconds:
            return None

        trigger = None
        clip_length = ClipLength.SHORT_30

        # 1. Hot stock: stock moves > 5%
        if abs(stock_change_pct) > 5.0:
            trigger = ClipTrigger.HOT_STOCK
            clip_length = ClipLength.MEDIUM_60

        # 2. High interaction: danmu + likes spike
        elif danmu_count > 50 and like_count > 100:
            trigger = ClipTrigger.HIGH_INTERACTION
            clip_length = ClipLength.SHORT_30

        # 3. Gift peak: high-value gift moment
        elif gift_value >= 100.0:
            trigger = ClipTrigger.GIFT_PEAK
            clip_length = ClipLength.SHORT_30

        # 4. Memorable commentary
        elif segment_data and segment_data.get("is_highlight", False):
            trigger = ClipTrigger.MEMORABLE
            clip_length = ClipLength.LONG_90

        if trigger is None:
            return None

        # Create clip task
        duration_sec = 30 if clip_length == ClipLength.SHORT_30 else (60 if clip_length == ClipLength.MEDIUM_60 else 90)

        clip = ClipTask(
            trigger=trigger,
            clip_length=clip_length,
            start_time=max(0, now - duration_sec - self._last_clip_time),
            end_time=now - self._last_clip_time if self._last_clip_time else now,
            source_type="script",
            segment_id=segment_data.get("segment_id", "") if segment_data else "",
            title=self._generate_title(trigger, segment_data),
            description=self._generate_description(trigger, clip_length),
        )

        self._last_clip_time = now
        self._total_clips += 1
        self._clip_history.append(clip)
        logger.info("ClipGenerator: triggered %s (length=%s)", trigger.value, clip_length.value)

        return clip

    def _generate_title(self, trigger: ClipTrigger, segment_data: dict | None) -> str:
        """Generate a clip title."""
        if trigger == ClipTrigger.HOT_STOCK:
            stock = segment_data.get("topic", "某股") if segment_data else "热门股票"
            return f"{stock}异动分析"
        elif trigger == ClipTrigger.HIGH_INTERACTION:
            return "直播间高能时刻"
        elif trigger == ClipTrigger.GIFT_PEAK:
            return "感谢老板大气支持"
        elif trigger == ClipTrigger.MEMORABLE:
            return "老张精彩点评"
        return "精彩片段"

    def _generate_description(self, trigger: ClipTrigger, length: ClipLength) -> str:
        return f"AI财经直播间-{trigger.value}-{length.value}"

    def manual_clip(
        self, start_time: float, end_time: float,
        title: str = "手动切片", source: str = "video",
    ) -> ClipTask:
        """Manually create a clip task."""
        duration = end_time - start_time
        if duration <= 30:
            length = ClipLength.SHORT_30
        elif duration <= 60:
            length = ClipLength.MEDIUM_60
        else:
            length = ClipLength.LONG_90

        clip = ClipTask(
            trigger=ClipTrigger.MANUAL,
            clip_length=length,
            start_time=start_time,
            end_time=end_time,
            title=title,
            source_type=source,
        )
        self._clip_history.append(clip)
        # 24h: 裁剪旧记录
        if len(self._clip_history) > self._clip_history_max:
            self._clip_history = self._clip_history[-250:]
        self._total_clips += 1
        logger.info("ClipGenerator: manual clip created (%s)", clip.clip_id)
        return clip

    def get_stats(self) -> dict:
        return {
            "total_clips": self._total_clips,
            "recent_clips": [
                c.to_dict() for c in self._clip_history[-10:]
            ],
            "output_dir": self.output_dir,
        }
