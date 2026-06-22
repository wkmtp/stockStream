"""总导演 AI — 控制整个直播节奏和节目编排。

类似电视财经频道导演系统，负责：
  1. 节目编排 (rundown)
  2. 内容调度 (content pipeline)
  3. 互动管理 (engagement pipeline)
  4. 运营优化 (operation pipeline)

核心原则:
  - 直播间永远有内容
  - 永远有互动
  - 永远有画面变化
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum

from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


class ContentPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


class SegmentType(Enum):
    MARKET_OPENING = "market_opening"
    STOCK_ANALYSIS = "stock_analysis"
    DUAL_DIALOGUE = "dual_dialogue"
    DANMU_QA = "danmu_qa"
    NEWS_BRIEF = "news_brief"
    FUN_FACT = "fun_fact"
    GIFT_THANKS = "gift_thanks"
    TRAFFIC_CTA = "traffic_cta"
    AD_BREAK = "ad_break"
    CLIP_MARKER = "clip_marker"
    CLOSING = "closing"


@dataclass
class DirectorDecision:
    """总导演决策。"""
    next_action: str = ""
    priority: ContentPriority = ContentPriority.NORMAL
    reason: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "next_action": self.next_action,
            "priority": self.priority.value,
            "reason": self.reason,
        }


@dataclass
class RundownItem:
    """节目单条目。"""
    segment: SegmentType
    title: str = ""
    duration_seconds: int = 0
    priority: ContentPriority = ContentPriority.NORMAL

    def to_dict(self) -> dict:
        return {
            "segment": self.segment.value,
            "title": self.title,
            "duration_seconds": self.duration_seconds,
            "priority": self.priority.value,
        }


@dataclass
class ShowSchedule:
    """节目编排表。"""
    segment_duration: int = 120
    market_analysis_interval: int = 300
    silence_threshold: int = 30
    traffic_interval_minutes: int = 15
    monetization_interval_minutes: int = 30

    def build_rundown(self) -> list[RundownItem]:
        """生成默认节目单。"""
        return [
            RundownItem(SegmentType.MARKET_OPENING, "今日开盘解析", 45, ContentPriority.CRITICAL),
            RundownItem(SegmentType.STOCK_ANALYSIS, "热门个股分析", 60, ContentPriority.HIGH),
            RundownItem(SegmentType.DANMU_QA, "弹幕互动问答", 30, ContentPriority.NORMAL),
            RundownItem(SegmentType.DUAL_DIALOGUE, "双主播行情讨论", 60, ContentPriority.HIGH),
            RundownItem(SegmentType.NEWS_BRIEF, "财经新闻速报", 30, ContentPriority.NORMAL),
            RundownItem(SegmentType.FUN_FACT, "财经趣闻", 15, ContentPriority.LOW),
            RundownItem(SegmentType.TRAFFIC_CTA, "关注引导", 10, ContentPriority.LOW),
            RundownItem(SegmentType.CLIP_MARKER, "切片标记", 5, ContentPriority.LOW),
        ]


class ChiefDirector:
    """总导演 AI — 直播系统的大脑。

    负责:
      1. 节目编排调度
      2. 内容流水线管理
      3. 互动 流水线管理
      4. 运营流水线管理
      5. 质量监控

    通过事件总线与其他所有模块通讯，不直接依赖任何业务模块。
    """

    def __init__(self, config: ShowSchedule | None = None,
                 bus: EventBus | None = None) -> None:
        self.config = config or ShowSchedule()
        self._bus: EventBus | None = bus
        self._rundown: list[RundownItem] = self.config.build_rundown()
        self._current_index = 0
        self._running = False
        self._task: asyncio.Task | None = None
        self._decisions: list[DirectorDecision] = []
        self._intervention_queue: asyncio.Queue[DirectorDecision] = asyncio.Queue()

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    # ── Lifecycle ──────────────────────────────────────────────────

    async def start(self) -> None:
        """启动总导演（自动驾驶模式）。"""
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        bus = await self.bus

        # 订阅关键事件
        @bus.on("danmu.processed", priority=100)
        async def _on_danmu(event):
            await self._evaluate_danmu(event)

        @bus.on("live.gift_action", priority=100)
        async def _on_gift(event):
            await self._evaluate_gift(event)

        @bus.on("live.engagement_action", priority=90)
        async def _on_engagement(event):
            await self._evaluate_engagement(event)

        logger.info("ChiefDirector started — auto-pilot engaged")
        await bus.emit_async("director.show_started", {
            "rundown": [r.to_dict() for r in self._rundown],
        })

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        bus = await self.bus
        await bus.emit_async("director.show_ended", {})
        logger.info("ChiefDirector stopped")

    # ── Main Loop ──────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        """主循环 — 按节目单推进。"""
        bus = await self.bus
        while self._running:
            try:
                # 处理外部干预
                self._process_intervention()

                # 获取当前节目
                item = self._current_rundown_item()
                if item:
                    await self._execute_segment(item)
                    self._current_index = (self._current_index + 1) % len(self._rundown)

                # 检查运营指标
                await self._operation_check()

                await asyncio.sleep(self.config.segment_duration)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("ChiefDirector loop error: %s", exc)
                await asyncio.sleep(5)

    # ── Content Pipeline ───────────────────────────────────────────

    async def _execute_segment(self, item: RundownItem) -> None:
        """执行一个节目段。"""
        bus = await self.bus
        await bus.emit_async("director.segment_start", {
            "segment": item.to_dict(),
        })

        if item.segment == SegmentType.STOCK_ANALYSIS:
            await bus.emit_async("director.action", {
                "action": "stock_analysis",
                "title": item.title,
            })
        elif item.segment == SegmentType.DUAL_DIALOGUE:
            await bus.emit_async("director.action", {
                "action": "dual_dialogue",
                "title": item.title,
            })
        elif item.segment == SegmentType.DANMU_QA:
            await bus.emit_async("director.action", {
                "action": "danmu_qa",
            })
        elif item.segment == SegmentType.NEWS_BRIEF:
            await bus.emit_async("director.action", {
                "action": "news_brief",
            })
        elif item.segment == SegmentType.FUN_FACT:
            await bus.emit_async("director.action", {
                "action": "fun_fact",
            })
        elif item.segment == SegmentType.TRAFFIC_CTA:
            await bus.emit_async("director.action", {
                "action": "traffic_cta",
            })
        elif item.segment == SegmentType.CLIP_MARKER:
            await bus.emit_async("director.action", {
                "action": "clip_marker",
            })

        # 决策记录
        decision = DirectorDecision(
            next_action=item.segment.value,
            priority=item.priority,
            reason=f"Rundown #{self._current_index}",
        )
        self._decisions.append(decision)

    # ── Evaluation ─────────────────────────────────────────────────

    async def _evaluate_danmu(self, event) -> None:
        """评估弹幕是否需要优先处理。"""
        data = event.data or {}
        tags = data.get("tags", [])
        if "stock_question" in tags:
            decision = DirectorDecision(
                next_action="danmu_qa",
                priority=ContentPriority.HIGH,
                reason=f"Stock question from {data.get('username', '')}",
            )
            await self._intervention_queue.put(decision)

    async def _evaluate_gift(self, event) -> None:
        """评估礼物是否需要感谢。"""
        data = event.data or {}
        if data.get("level") == "super":
            decision = DirectorDecision(
                next_action="gift_thanks",
                priority=ContentPriority.CRITICAL,
                reason=f"Super gift from {data.get('user', '')}",
            )
            await self._intervention_queue.put(decision)

    async def _evaluate_engagement(self, event) -> None:
        """评估互动数据。"""
        data = event.data or {}
        if data.get("level") == "super":
            decision = DirectorDecision(
                next_action="engagement_response",
                priority=ContentPriority.HIGH,
                reason=f"High engagement: {data.get('message', '')}",
            )
            await self._intervention_queue.put(decision)

    async def _operation_check(self) -> None:
        """运营指标巡检。"""
        bus = await self.bus
        await bus.emit_async("director.operation_check", {
            "timestamp": time.time(),
        })

    def _process_intervention(self) -> None:
        """处理外部干预队列。"""
        try:
            while True:
                decision = self._intervention_queue.get_nowait()
                self._decisions.append(decision)
                logger.info("Director intervention: %s (priority=%s)",
                           decision.next_action, decision.priority.value)
        except asyncio.QueueEmpty:
            pass

    # ── Query ──────────────────────────────────────────────────────

    def _current_rundown_item(self) -> RundownItem | None:
        if not self._rundown:
            return None
        return self._rundown[self._current_index]

    def get_rundown(self) -> dict:
        """获取当前节目单。"""
        return {
            "current_index": self._current_index,
            "current_segment": self._current_rundown_item().to_dict() if self._rundown else None,
            "rundown": [r.to_dict() for r in self._rundown],
            "recent_decisions": [d.to_dict() for d in self._decisions[-10:]],
        }

    def get_stats(self) -> dict:
        return {
            "is_running": self._running,
            "rundown_items": len(self._rundown),
            "current_index": self._current_index,
            "total_decisions": len(self._decisions),
        }
