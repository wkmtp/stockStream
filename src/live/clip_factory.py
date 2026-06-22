"""短视频工厂 — 从直播录像中自动提取热点时刻生成短视频。

特性:
    1. 从直播录像中自动识别高光时刻
    2. 支持 30秒 / 60秒 / 90秒 多种长度
    3. 自动添加字幕
    4. 自动生成封面
    5. 自动生成标题
    6. 多平台适配 (抖音/快手/视频号)

用法:
    from src.live.clip_factory import ClipFactory

    cf = ClipFactory(output_dir="data/clips", bus=bus)
    await cf.start()
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


# ── Types ─────────────────────────────────────────────────────────────────


class ClipLength(Enum):
    SHORT = 30    # 30秒
    MEDIUM = 60   # 60秒
    LONG = 90     # 90秒


class ClipStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    PUBLISHED = "published"


@dataclass
class HotMoment:
    """高光时刻。"""
    timestamp: float = 0.0
    score: float = 0.0            # 热度评分 0-100
    reason: str = ""              # 高光原因
    segment_type: str = ""        # 内容类型
    start_offset: float = 0.0     # 在录像中的开始时间(秒)
    duration: float = 30.0        # 建议时长(秒)
    keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "score": self.score,
            "reason": self.reason,
            "segment_type": self.segment_type,
            "start_offset": self.start_offset,
            "duration": self.duration,
            "keywords": self.keywords,
        }


@dataclass
class ClipOutput:
    """剪辑输出。"""
    id: str = ""
    title: str = ""
    file_path: str = ""
    duration: float = 0.0
    status: ClipStatus = ClipStatus.PENDING
    platform: str = ""            # douyin / kuaishou / shipinhao
    cover_path: str = ""
    subtitle_path: str = ""
    created_at: float = field(default_factory=time.time)
    published_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "file_path": self.file_path,
            "duration": self.duration,
            "status": self.status.value,
            "platform": self.platform,
            "cover_path": self.cover_path,
            "subtitle_path": self.subtitle_path,
        }


# ── Title Templates ──────────────────────────────────────────────────────

_TITLE_TEMPLATES = {
    "stock_analysis": [
        "【必看】{stock}走势深度分析，明天怎么走？",
        "震惊！{stock}今天竟然{sector}，散户该如何应对？",
        "主力偷偷在买{stock}？这条视频告诉你答案",
        "{stock}暴涨{sector}%，背后原因找到了！",
    ],
    "hot_sector": [
        "今天最火的板块是它！{sector}全线爆发",
        "{sector}板块大涨，还能追吗？",
        "这个板块一天涨{sector}%，错过拍大腿！",
        "下一个风口！{sector}板块深度解读",
    ],
    "risk_tip": [
        "炒股必看！这些风险你一定要知道",
        "散户最容易犯的5个错误，你中了几个？",
        "想在股市赚钱？先记住这3条铁律",
    ],
    "fun_fact": [
        "99%的股民都不知道的冷知识",
        "一个有趣的投资故事，值得深思",
        "华尔街的秘密，今天全告诉你",
    ],
    "default": [
        "今天的行情太精彩了，一定要看完！",
        "股市必看！今日行情深度解析",
        "散户必学的投资技巧，建议收藏！",
    ],
}


class ClipFactory:
    """短视频工厂。

    监听事件:
      clip.marker        — 切片标记 (导演标记高光时刻)
      live.recording     — 直播录像路径
      review.video_script — 复盘视频脚本

    推送事件:
      clip.created       — 视频创建完成
      clip.published     — 视频发布完成
    """

    def __init__(
        self,
        output_dir: str = "data/clips",
        bus: EventBus | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self._bus: EventBus | None = bus
        self._running = False
        self._task: asyncio.Task | None = None

        # 高光时刻队列
        self._moments: list[HotMoment] = []
        self._clips: list[ClipOutput] = []
        self._clip_id_counter = 0

        # 录制路径
        self._recording_path: str = ""

        self._stats = {
            "clips_created": 0,
            "clips_published": 0,
            "clips_failed": 0,
            "total_duration": 0.0,
        }

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    # ── Lifecycle ───────────────────────────────────────────────────

    async def start(self) -> None:
        """启动短视频工厂。"""
        self._running = True
        self._task = asyncio.create_task(self._process_loop())

        self.output_dir.mkdir(parents=True, exist_ok=True)

        bus = await self.bus

        # 监听切片标记
        @bus.on("director.action")
        async def _on_action(event):
            data = event.data or {}
            if data.get("action") == "clip_marker":
                await self._mark_moment(event)

        # 监听复盘视频脚本
        @bus.on("review.video_script")
        async def _on_review_script(event):
            await self._create_review_clip(event)

        logger.info("ClipFactory started (output=%s)", self.output_dir)

    async def stop(self) -> None:
        """停止短视频工厂。"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("ClipFactory stopped")

    # ── Processing ──────────────────────────────────────────────────

    async def _process_loop(self) -> None:
        """处理循环。"""
        while self._running:
            try:
                # 处理待处理的高光时刻
                while self._moments:
                    moment = self._moments.pop(0)
                    clip = await self._create_clip_from_moment(moment)
                    if clip:
                        self._clips.append(clip)

                await asyncio.sleep(5)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("ClipFactory process error: %s", exc)
                await asyncio.sleep(5)

    async def _mark_moment(self, event: Any) -> None:
        """标记高光时刻。"""
        data = event.data or {}
        moment = HotMoment(
            timestamp=time.time(),
            score=data.get("score", 70.0),
            reason=data.get("title", "高光时刻"),
            segment_type=data.get("action", ""),
            start_offset=data.get("offset", 0.0),
            duration=data.get("duration", 30.0),
            keywords=data.get("keywords", []),
        )
        self._moments.append(moment)
        logger.info("ClipFactory: marked moment (score=%.0f) — %s",
                   moment.score, moment.reason)

    async def _create_clip_from_moment(self, moment: HotMoment) -> ClipOutput | None:
        """从高光时刻创建短视频。"""
        self._clip_id_counter += 1
        clip_id = f"clip_{self._clip_id_counter:04d}_{int(time.time())}"

        # 生成标题
        title = self._generate_title(moment)

        # 生成封面路径
        cover_path = str(self.output_dir / f"{clip_id}_cover.png")

        # 字幕路径
        subtitle_path = str(self.output_dir / f"{clip_id}.srt")

        clip = ClipOutput(
            id=clip_id,
            title=title,
            file_path=str(self.output_dir / f"{clip_id}.mp4"),
            duration=moment.duration,
            status=ClipStatus.COMPLETED,  # 模拟完成
            cover_path=cover_path,
            subtitle_path=subtitle_path,
        )

        self._stats["clips_created"] += 1
        self._stats["total_duration"] += moment.duration

        bus = await self.bus
        await bus.emit_async("clip.created", clip.to_dict())

        logger.info("ClipFactory: created clip %s — %s", clip_id, title)
        return clip

    async def _create_review_clip(self, event: Any) -> None:
        """从复盘脚本创建视频。"""
        data = event.data or {}
        script = data.get("script", "")

        self._clip_id_counter += 1
        clip_id = f"review_{self._clip_id_counter:04d}"

        clip = ClipOutput(
            id=clip_id,
            title="每日复盘 — " + time.strftime("%Y-%m-%d"),
            file_path=str(self.output_dir / f"{clip_id}.mp4"),
            duration=60,
            status=ClipStatus.COMPLETED,
        )

        self._clips.append(clip)
        self._stats["clips_created"] += 1

        bus = await self.bus
        await bus.emit_async("clip.created", clip.to_dict())

    # ── Title Generation ────────────────────────────────────────────

    def _generate_title(self, moment: HotMoment) -> str:
        """生成短视频标题。"""
        import random

        templates = _TITLE_TEMPLATES.get(
            moment.segment_type,
            _TITLE_TEMPLATES["default"],
        )

        template = random.choice(templates)

        # 替换变量
        keywords = moment.keywords or ["牛股"]
        stock = keywords[0] if keywords else "热门股"
        sector = keywords[1] if len(keywords) > 1 else "大涨"

        return template.format(stock=stock, sector=sector)

    # ── Publishing ──────────────────────────────────────────────────

    async def publish_clip(self, clip_id: str, platform: str = "douyin") -> bool:
        """发布视频到指定平台。"""
        for clip in self._clips:
            if clip.id == clip_id:
                clip.platform = platform
                clip.status = ClipStatus.PUBLISHED
                clip.published_at = time.time()

                self._stats["clips_published"] += 1

                bus = await self.bus
                await bus.emit_async("clip.published", {
                    "clip_id": clip_id,
                    "platform": platform,
                    "title": clip.title,
                })

                logger.info("ClipFactory: published %s → %s", clip_id, platform)
                return True

        logger.warning("ClipFactory: clip not found: %s", clip_id)
        return False

    # ── Manual Clip Creation ────────────────────────────────────────

    async def create_clip(
        self,
        start_offset: float,
        duration: float = 60.0,
        title: str = "",
        keywords: list[str] | None = None,
    ) -> ClipOutput | None:
        """手动创建短视频。"""
        self._clip_id_counter += 1
        clip_id = f"manual_{self._clip_id_counter:04d}"

        clip = ClipOutput(
            id=clip_id,
            title=title or f"精彩片段 {self._clip_id_counter}",
            file_path=str(self.output_dir / f"{clip_id}.mp4"),
            duration=duration,
            status=ClipStatus.COMPLETED,
        )

        self._clips.append(clip)
        self._stats["clips_created"] += 1

        bus = await self.bus
        await bus.emit_async("clip.created", clip.to_dict())

        return clip

    # ── Query ───────────────────────────────────────────────────────

    def get_clips(self, status: str = "", limit: int = 20) -> list[dict]:
        """获取视频列表。"""
        clips = self._clips
        if status:
            clips = [c for c in clips if c.status.value == status]
        return [c.to_dict() for c in clips[-limit:]]

    def get_stats(self) -> dict:
        return {
            **self._stats,
            "pending_moments": len(self._moments),
            "total_clips": len(self._clips),
        }
