"""直播内容调度器 — 控制直播节奏，避免重复内容。

特性:
    1. 周期性内容轮转: 股票分析 → 热点板块 → 新闻点评 → 观众互动 → 财经趣闻 → 风险提示
    2. 内容去重: 避免在短时间内重复讨论同一股票/话题
    3. 自适应调度: 根据市场状态、观众活跃度动态调整
    4. 内容池管理: 预生成内容缓存，保证流畅切换

用法:
    from src.scheduler.content import ContentScheduler

    cs = ContentScheduler()
    cs.register_cycle(["stock_analysis", "hot_sector", "news_brief",
                        "audience_interaction", "fun_fact", "risk_tip"])
    await cs.start()
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum

from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)

# ── 24h 稳定性常量 ──
_MAX_POOL_PER_TYPE = 200  # 每种内容类型池子上限


# ── Types ─────────────────────────────────────────────────────────────────


class ContentType(Enum):
    """内容类型。"""
    STOCK_ANALYSIS = "stock_analysis"         # 个股分析
    HOT_SECTOR = "hot_sector"                 # 热点板块
    NEWS_BRIEF = "news_brief"                 # 新闻点评
    AUDIENCE_INTERACTION = "audience_interaction"  # 观众互动
    FUN_FACT = "fun_fact"                     # 财经趣闻
    RISK_TIP = "risk_tip"                     # 风险提示
    MARKET_OVERVIEW = "market_overview"       # 大盘概览
    KNOWLEDGE_SHARE = "knowledge_share"       # 知识分享
    TRADING_REVIEW = "trading_review"         # 交易回顾
    QUIZ = "quiz"                             # 有奖问答


@dataclass
class ContentSegment:
    """内容段。"""
    content_type: ContentType
    title: str = ""
    script: str = ""
    duration_seconds: int = 60
    priority: int = 0
    related_symbols: list[str] = field(default_factory=list)
    used_at: float = 0.0
    cooldown_seconds: int = 300  # 冷却时间

    def to_dict(self) -> dict:
        return {
            "type": self.content_type.value,
            "title": self.title,
            "script": self.script,
            "duration_seconds": self.duration_seconds,
            "priority": self.priority,
            "related_symbols": self.related_symbols,
        }


@dataclass
class ScheduleConfig:
    """调度配置。"""
    cycle_duration_seconds: int = 3600  # 一个完整周期的时长
    segment_min_duration: int = 30      # 最小段时长
    segment_max_duration: int = 120     # 最大段时长
    default_cooldown: int = 600         # 默认冷却时间 (10分钟)
    max_history_symbols: int = 50       # 记录最近分析的股票数
    dedup_window_seconds: int = 1800    # 去重窗口 (30分钟)
    market_open_only: bool = False      # 是否仅在开盘时调度


class ContentScheduler:
    """直播内容调度器。

    推送事件:
      content.next_segment      — 下一个内容段
      content.cycle_completed   — 周期完成
      content.segment_skipped   — 内容被跳过（去重/冷却）
    """

    def __init__(
        self,
        config: ScheduleConfig | None = None,
        bus: EventBus | None = None,
    ) -> None:
        self.config = config or ScheduleConfig()
        self._bus: EventBus | None = bus
        self._running = False
        self._task: asyncio.Task | None = None

        # 内容周期
        self._cycle: list[ContentType] = []
        self._current_index = 0

        # 内容池
        self._content_pool: dict[ContentType, list[ContentSegment]] = {}
        for ct in ContentType:
            self._content_pool[ct] = []

        # 去重记录
        self._recent_symbols: list[tuple[str, float]] = []  # (symbol, timestamp)
        self._recent_topics: list[tuple[str, float]] = []   # (topic, timestamp)

        # 统计
        self._segments_served = 0
        self._segments_skipped = 0
        self._cycles_completed = 0

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    # ── Configuration ───────────────────────────────────────────────

    def register_cycle(self, cycle: list[str]) -> None:
        """注册内容周期。

        Example:
            cs.register_cycle([
                "stock_analysis", "hot_sector", "news_brief",
                "audience_interaction", "fun_fact", "risk_tip"
            ])
        """
        self._cycle = []
        for item in cycle:
            try:
                self._cycle.append(ContentType(item))
            except ValueError:
                logger.warning("Unknown content type: %s, skipping", item)
        logger.info("ContentScheduler: cycle registered (%d types)", len(self._cycle))

    def add_content(self, segment: ContentSegment) -> None:
        """向内容池添加内容段。"""
        pool = self._content_pool.get(segment.content_type, [])
        pool.append(segment)
        # 24h 稳定性：限制每类型池大小，防止内存无限增长
        if len(pool) > _MAX_POOL_PER_TYPE:
            del pool[:len(pool) - _MAX_POOL_PER_TYPE]
        # 按优先级排序
        pool.sort(key=lambda s: -s.priority)

    def add_contents(self, segments: list[ContentSegment]) -> None:
        """批量添加内容段。"""
        for seg in segments:
            self.add_content(seg)

    # ── Lifecycle ───────────────────────────────────────────────────

    async def start(self) -> None:
        """启动内容调度器。"""
        self._running = True
        self._task = asyncio.create_task(self._schedule_loop())

        bus = await self.bus

        # 24h 稳定性：记录所有订阅句柄，stop() 时取消
        self._subs: list[tuple[str, object]] = []

        # 订阅导演指令
        @bus.on("director.action")
        async def _on_director_action(event):
            data = event.data or {}
            action = data.get("action", "")
            if action:
                await self._handle_director_action(action, data)
        self._subs.append(("director.action", _on_director_action))

        # 订阅跳过请求
        @bus.on("content.skip")
        async def _on_skip(event):
            self._segments_skipped += 1
        self._subs.append(("content.skip", _on_skip))

        logger.info("ContentScheduler started (cycle=%d types)", len(self._cycle))

    async def stop(self) -> None:
        """停止内容调度器。"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # 24h 稳定性：取消所有 EventBus 订阅
        bus = await self.bus
        for pattern, handler in getattr(self, '_subs', []):
            bus.unsubscribe(pattern, handler)
        self._subs = []

        logger.info("ContentScheduler stopped")

    # ── Main Loop ───────────────────────────────────────────────────

    async def _schedule_loop(self) -> None:
        """调度主循环。"""
        bus = await self.bus
        while self._running:
            try:
                if not self._cycle:
                    await asyncio.sleep(5)
                    continue

                # 获取下一个内容类型
                content_type = self._cycle[self._current_index]
                segment = await self._pick_segment(content_type)

                if segment:
                    # 检查去重
                    if await self._is_duplicate(segment):
                        logger.debug("ContentScheduler: skipped duplicate %s", content_type.value)
                        self._segments_skipped += 1
                        await bus.emit_async("content.segment_skipped", {
                            "type": content_type.value,
                            "reason": "duplicate",
                        })
                    else:
                        # 发送内容段
                        self._segments_served += 1
                        segment.used_at = time.time()

                        await bus.emit_async("content.next_segment", segment.to_dict())

                        # 记录去重信息
                        self._record_dedup(segment)

                        # 等待段播放完毕
                        await asyncio.sleep(segment.duration_seconds)

                # 推进周期
                self._current_index = (self._current_index + 1) % len(self._cycle)

                # 周期完成
                if self._current_index == 0:
                    self._cycles_completed += 1
                    await bus.emit_async("content.cycle_completed", {
                        "cycle": self._cycles_completed,
                        "segments_served": self._segments_served,
                    })
                    logger.info("ContentScheduler: cycle %d completed", self._cycles_completed)

                await asyncio.sleep(2)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("ContentScheduler loop error: %s", exc)
                await asyncio.sleep(5)

    # ── Content Selection ───────────────────────────────────────────

    async def _pick_segment(self, content_type: ContentType) -> ContentSegment | None:
        """从内容池中选择最佳内容段。"""
        pool = self._content_pool.get(content_type, [])

        if not pool:
            # 没有缓存内容 → 发送请求生成
            bus = await self.bus
            await bus.emit_async("content.request_generation", {
                "type": content_type.value,
            })
            # 返回默认段
            return self._default_segment(content_type)

        # 选择可用的段（未在冷却期）
        now = time.time()
        available = [
            s for s in pool
            if now - s.used_at > s.cooldown_seconds
        ]

        if not available:
            # 全部在冷却期，选冷却最久的
            segment = min(pool, key=lambda s: s.used_at)
        else:
            # 优先高优先级，再随机
            max_priority = max(s.priority for s in available)
            top = [s for s in available if s.priority == max_priority]
            segment = random.choice(top)

        return segment

    async def _is_duplicate(self, segment: ContentSegment) -> bool:
        """检查是否为重复内容。"""
        now = time.time()

        # 检查股票是否近期已分析
        for symbol in segment.related_symbols:
            for s, ts in self._recent_symbols:
                if s == symbol and now - ts < self.config.dedup_window_seconds:
                    return True

        # 检查标题是否近期使用过
        for topic, ts in self._recent_topics:
            if topic == segment.title and now - ts < self.config.dedup_window_seconds:
                return True

        return False

    def _record_dedup(self, segment: ContentSegment) -> None:
        """记录去重信息。"""
        now = time.time()
        for symbol in segment.related_symbols:
            self._recent_symbols.append((symbol, now))

        if segment.title:
            self._recent_topics.append((segment.title, now))

        # 清理过期记录
        cutoff = now - self.config.dedup_window_seconds
        self._recent_symbols = [(s, t) for s, t in self._recent_symbols if t > cutoff]
        self._recent_topics = [(s, t) for s, t in self._recent_topics if t > cutoff]

        # 限制大小
        if len(self._recent_symbols) > self.config.max_history_symbols:
            self._recent_symbols = self._recent_symbols[-self.config.max_history_symbols:]

    def _default_segment(self, content_type: ContentType) -> ContentSegment:
        """生成默认内容段。"""
        defaults = {
            ContentType.STOCK_ANALYSIS: ContentSegment(
                ContentType.STOCK_ANALYSIS,
                "今日个股分析", "让我们来看看今日的个股表现...",
                60, related_symbols=["600519"],
            ),
            ContentType.HOT_SECTOR: ContentSegment(
                ContentType.HOT_SECTOR,
                "热点板块扫描", "今日热点板块方面...",
                45,
            ),
            ContentType.NEWS_BRIEF: ContentSegment(
                ContentType.NEWS_BRIEF,
                "财经新闻速报", "最新财经消息...",
                30,
            ),
            ContentType.AUDIENCE_INTERACTION: ContentSegment(
                ContentType.AUDIENCE_INTERACTION,
                "观众互动环节", "来看看大家的弹幕提问...",
                30,
            ),
            ContentType.FUN_FACT: ContentSegment(
                ContentType.FUN_FACT,
                "财经趣闻", "分享一个有趣的财经小知识...",
                15,
            ),
            ContentType.RISK_TIP: ContentSegment(
                ContentType.RISK_TIP,
                "风险提示", "温馨提示：投资有风险...",
                15,
            ),
            ContentType.MARKET_OVERVIEW: ContentSegment(
                ContentType.MARKET_OVERVIEW,
                "大盘概览", "今日大盘整体走势...",
                45,
            ),
            ContentType.KNOWLEDGE_SHARE: ContentSegment(
                ContentType.KNOWLEDGE_SHARE,
                "投资知识分享", "今天给大家分享一个投资小技巧...",
                30,
            ),
            ContentType.TRADING_REVIEW: ContentSegment(
                ContentType.TRADING_REVIEW,
                "交易回顾", "回顾一下近期的交易表现...",
                30,
            ),
            ContentType.QUIZ: ContentSegment(
                ContentType.QUIZ,
                "有奖问答", "来参与有奖问答吧...",
                20,
            ),
        }
        return defaults.get(content_type, ContentSegment(
            content_type, str(content_type.value), "", 30,
        ))

    # ── Director Actions ────────────────────────────────────────────

    async def _handle_director_action(self, action: str, data: dict) -> None:
        """处理导演指令。"""
        bus = await self.bus
        try:
            content_type = ContentType(action)
            segment = await self._pick_segment(content_type)
            if segment:
                await bus.emit_async("content.next_segment", segment.to_dict())
        except ValueError:
            pass

    # ── Force Operations ────────────────────────────────────────────

    async def force_segment(self, content_type: str) -> ContentSegment | None:
        """强制推送指定类型内容。"""
        try:
            ct = ContentType(content_type)
            segment = await self._pick_segment(ct)
            if segment:
                bus = await self.bus
                await bus.emit_async("content.next_segment", segment.to_dict())
            return segment
        except ValueError:
            return None

    async def skip_current(self) -> None:
        """跳过当前内容段。"""
        self._current_index = (self._current_index + 1) % len(self._cycle)
        bus = await self.bus
        await bus.emit_async("content.segment_skipped", {"reason": "manual"})

    # ── Query ───────────────────────────────────────────────────────

    def get_pool_stats(self) -> dict[str, int]:
        """获取内容池统计。"""
        return {
            ct.value: len(segments)
            for ct, segments in self._content_pool.items()
        }

    def get_stats(self) -> dict:
        return {
            "cycle_size": len(self._cycle),
            "current_index": self._current_index,
            "segments_served": self._segments_served,
            "segments_skipped": self._segments_skipped,
            "cycles_completed": self._cycles_completed,
            "pool_stats": self.get_pool_stats(),
            "recent_symbols_count": len(self._recent_symbols),
        }
