"""Chief Director Agent — the "总导演 AI" that controls the entire live show.

Responsibilities:
- Control overall live room pacing
- Manage: market analysis, dual-host dialogue, chart switching,
  danmu interaction, gift thanks, hot news, finance fun,
  ad insertion, short video clips
- Ensure: room never goes silent, always has interaction,
  always has visual changes

Goals:
- Increase retention rate (停留率)
- Increase interaction rate (互动率)
- Increase follow rate (关注率)
- Increase conversion rate (转化率)

Architecture::

    ChiefDirectorAgent (总导演)
    ├── Schedule Engine (节目编排)
    ├── Content Pipeline (内容流水线)
    │   ├── stock_analysis → DualHostService
    │   ├── news_commentary → NewsCommentator
    │   ├── finance_fun → FinanceHumorEngine
    │   └── audience_qa → StockQAAgent
    ├── Interaction Pipeline (互动流水线)
    │   ├── danmu_center → DanmuCenter
    │   ├── engagement → EngagementAgent
    │   ├── gift → GiftAgent
    │   └── anti_silence → AntiSilenceAgent
    ├── Operation Pipeline (运营流水线)
    │   ├── traffic → TrafficAgent
    │   ├── monetization → MonetizationAgent
    │   ├── operation → OperationAgent
    │   └── fan_tracker → FanGrowthTracker
    ├── Content Pipeline (内容输出)
    │   ├── clip_generator → ClipGenerator
    │   └── short_video → ShortVideoWriter
    └── Dashboard → LiveDashboard

Like a TV finance channel director system.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from stockstream.platform_gateway.common.models import (
    CommentEvent, GiftEvent, GiftLevel, LikeEvent, FollowEvent, ViewerEvent,
    Platform,
)

logger = logging.getLogger(__name__)


# ── Director phases ──────────────────────────────────────────────

class DirectorPhase(str, Enum):
    """Phases of the live show."""
    WARMING_UP = "warming_up"             # 暖场 (first 5 min)
    ACTIVE_SESSION = "active_session"     # 正式直播 (main loop)
    ENGAGEMENT_PUSH = "engagement_push"   # 互动冲刺
    WRAPPING_UP = "wrapping_up"           # 结束收尾


# ── Content priority ─────────────────────────────────────────────

class ContentPriority(int, Enum):
    CRITICAL = 0       # Must play immediately (gift peak, market flash)
    HIGH = 1           # Important (hot stock, Q&A)
    NORMAL = 2         # Regular schedule
    LOW = 3            # Fill content (jokes, recap)
    BACKGROUND = 4     # Can skip


@dataclass(slots=True)
class DirectorDecision:
    """A scheduling decision from the chief director."""
    decision_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    phase: DirectorPhase = DirectorPhase.ACTIVE_SESSION
    next_action: str = ""                 # what to do next
    action_data: dict[str, Any] = field(default_factory=dict)
    priority: ContentPriority = ContentPriority.NORMAL
    reason: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "decision_id": self.decision_id,
            "phase": self.phase.value,
            "next_action": self.next_action,
            "action_data": self.action_data,
            "priority": self.priority.name,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


# ── Default Show Schedule ───────────────────────────────────────

@dataclass(slots=True)
class ShowSchedule:
    """Define what the director should run and at what intervals."""
    # Segment intervals in seconds
    stock_analysis_interval: int = 180       # every 3 min
    hot_sector_interval: int = 600           # every 10 min
    news_commentary_interval: int = 900      # every 15 min
    finance_fun_interval: int = 1200         # every 20 min
    audience_qa_interval: int = 1800         # every 30 min
    market_review_interval: int = 3600       # every 60 min

    # Operation intervals
    traffic_cta_interval: int = 900          # every 15 min
    monetization_interval: int = 1800        # every 30 min

    # Anti-silence
    silence_threshold: int = 30              # seconds

    # Pacing
    max_segment_duration: int = 90           # max seconds per segment
    min_gap_between_segments: int = 10       # seconds


class ChiefDirectorAgent:
    """Master AI director controlling the entire live broadcast.

    This is the brain of the operation — it decides what happens
    next, when to switch topics, when to push engagement, and
    how to keep the room alive 24/7.

    Usage::

        director = ChiefDirectorAgent(config=ShowSchedule())
        director.register_handler("stock_analysis", async_handler)
        director.register_handler("traffic_cta", sync_handler)
        await director.start()
    """

    def __init__(
        self,
        config: ShowSchedule | None = None,
        tick_interval: float = 1.0,
    ) -> None:
        self.config = config or ShowSchedule()
        self.tick_interval = tick_interval

        # ── Handlers ──────────────────────────────────────────
        self._handlers: dict[str, Callable] = {}

        # ── State ──────────────────────────────────────────────
        self._running = False
        self._phase = DirectorPhase.WARMING_UP
        self._started_at: float = 0.0
        self._task: asyncio.Task | None = None

        # Timing trackers
        self._last_stock_analysis: float = 0.0
        self._last_hot_sector: float = 0.0
        self._last_news: float = 0.0
        self._last_fun: float = 0.0
        self._last_qa: float = 0.0
        self._last_market_review: float = 0.0
        self._last_traffic_cta: float = 0.0
        self._last_monetization: float = 0.0
        self._last_user_interaction: float = 0.0
        self._last_segment_end: float = 0.0

        # Decision log
        self._decision_log: deque[DirectorDecision] = deque(maxlen=200)
        self._decision_count = 0

        # Intervention queue (critical events jump the line)
        self._intervention_queue: asyncio.Queue[DirectorDecision] = asyncio.Queue(maxsize=50)

        # Sub-agent references (set after init)
        self.dual_host: Any = None
        self.danmu_center: Any = None
        self.stock_qa: Any = None
        self.engagement: Any = None
        self.gift: Any = None
        self.fan_tracker: Any = None
        self.traffic: Any = None
        self.anti_silence: Any = None
        self.monetization: Any = None
        self.operation: Any = None
        self.clip_gen: Any = None
        self.video_writer: Any = None
        self.dashboard: Any = None
        self.platform_gateway: Any = None

    def register_handler(self, action: str, handler: Callable) -> None:
        """Register a handler for a specific action type."""
        self._handlers[action] = handler

    # ── Lifecycle ─────────────────────────────────────────────

    async def start(self) -> None:
        """Start the director loop."""
        # 24h: 幂等性保护
        if self._running:
            return
        self._running = True
        self._started_at = time.time()
        self._phase = DirectorPhase.WARMING_UP

        # Opening sequence
        await self._dispatch("opening", {"phase": "warming_up"})

        self._phase = DirectorPhase.ACTIVE_SESSION
        self._task = asyncio.create_task(self._director_loop())
        logger.info("ChiefDirector started")

    async def stop(self) -> None:
        """Stop the director loop."""
        self._running = False
        self._phase = DirectorPhase.WRAPPING_UP

        # Closing sequence
        await self._dispatch("closing", {"phase": "wrapping_up"})

        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("ChiefDirector stopped (decisions=%d)", self._decision_count)

    async def _director_loop(self) -> None:
        """Main director loop — the heart of the operation."""
        while self._running:
            try:
                # 1. Check intervention queue first (critical events)
                decision = await self._check_interventions()

                # 2. If no intervention, follow schedule
                if decision is None:
                    decision = self._evaluate_schedule()

                # 3. Execute decision
                if decision:
                    await self._execute_decision(decision)

                # 4. Tick
                await asyncio.sleep(self.tick_interval)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Director loop error")
                await asyncio.sleep(5)

    # ── Schedule Evaluation ───────────────────────────────────

    async def _check_interventions(self) -> DirectorDecision | None:
        """Check for high-priority interventions."""
        try:
            return self._intervention_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    def _evaluate_schedule(self) -> DirectorDecision | None:
        """Evaluate the show schedule and decide what to do next."""
        now = time.time()
        uptime = now - self._started_at

        # Don't start a new segment if gap too short
        if now - self._last_segment_end < self.config.min_gap_between_segments:
            return None

        # Priority-ordered schedule check
        checks = [
            # (action, last_time, interval, priority, handler_key)
            ("stock_analysis", self._last_stock_analysis,
             self.config.stock_analysis_interval, ContentPriority.NORMAL),
            ("hot_sector", self._last_hot_sector,
             self.config.hot_sector_interval, ContentPriority.NORMAL),
            ("news_commentary", self._last_news,
             self.config.news_commentary_interval, ContentPriority.NORMAL),
            ("finance_fun", self._last_fun,
             self.config.finance_fun_interval, ContentPriority.LOW),
            ("audience_qa", self._last_qa,
             self.config.audience_qa_interval, ContentPriority.NORMAL),
            ("market_review", self._last_market_review,
             self.config.market_review_interval, ContentPriority.NORMAL),
        ]

        for action, last_time, interval, priority in checks:
            if uptime > interval and now - last_time >= interval:
                # Update tracker
                self._set_tracker(action, now)
                return DirectorDecision(
                    phase=self._phase,
                    next_action=action,
                    priority=priority,
                    reason=f"Scheduled {action} (interval={interval}s)",
                    timestamp=now,
                )

        # Operation checks (lower priority, check after content)
        if now - self._last_traffic_cta >= self.config.traffic_cta_interval:
            self._last_traffic_cta = now
            return DirectorDecision(
                phase=self._phase,
                next_action="traffic_cta",
                priority=ContentPriority.LOW,
                reason=f"Scheduled traffic CTA (interval={self.config.traffic_cta_interval}s)",
            )

        if now - self._last_monetization >= self.config.monetization_interval:
            self._last_monetization = now
            return DirectorDecision(
                phase=self._phase,
                next_action="monetization",
                priority=ContentPriority.LOW,
                reason="Scheduled monetization",
            )

        # Anti-silence check
        if now - self._last_user_interaction > self.config.silence_threshold:
            return DirectorDecision(
                phase=self._phase,
                next_action="anti_silence",
                priority=ContentPriority.HIGH,
                reason=f"Room silent for {int(now - self._last_user_interaction)}s",
            )

        return None

    def _set_tracker(self, action: str, now: float) -> None:
        """Update the timing tracker for a content action."""
        mapping = {
            "stock_analysis": "_last_stock_analysis",
            "hot_sector": "_last_hot_sector",
            "news_commentary": "_last_news",
            "finance_fun": "_last_fun",
            "audience_qa": "_last_qa",
            "market_review": "_last_market_review",
        }
        attr = mapping.get(action)
        if attr:
            setattr(self, attr, now)

    # ── Decision Execution ────────────────────────────────────

    async def _execute_decision(self, decision: DirectorDecision) -> None:
        """Execute a director's decision."""
        self._decision_count += 1
        self._decision_log.append(decision)
        self._last_segment_end = time.time()

        action = decision.next_action
        logger.debug("Director: executing %s (priority=%s, reason=%s)",
                      action, decision.priority.name, decision.reason)

        if action in self._handlers:
            try:
                handler = self._handlers[action]
                if asyncio.iscoroutinefunction(handler):
                    await handler(decision)
                else:
                    handler(decision)
            except Exception:
                logger.exception("Handler failed for %s", action)
        else:
            # Try dispatching to default handler
            await self._dispatch(action, decision.action_data)

        # Update dashboard
        if self.dashboard:
            self.dashboard.add_segment()

    async def _dispatch(self, action: str, data: dict) -> None:
        """Default dispatch to sub-systems."""
        logger.debug("Director dispatch: %s", action)

        if action == "stock_analysis" and self.dual_host:
            # Delegate to dual host
            from stockstream.dual_host.models import ShowSegmentType
            await self.dual_host.request_segment(ShowSegmentType.STOCK_ANALYSIS)

        elif action == "gift_thanks" and self.gift:
            interaction = self.gift.on_gift(
                username=data.get("username", ""),
                gift_name=data.get("gift_name", ""),
                gift_value=data.get("gift_value", 0.0),
                gift_level=data.get("gift_level", GiftLevel.NORMAL),
                platform=data.get("platform", ""),
            )
            if interaction:
                await self._announce(interaction.message)

        elif action == "traffic_cta" and self.traffic:
            cta = self.traffic.should_trigger()
            if cta:
                await self._announce(cta.message)
                if self.dashboard:
                    self.dashboard.add_traffic_cta()

        elif action == "monetization" and self.monetization:
            ad = self.monetization.should_trigger()
            if ad:
                await self._announce(ad.message)
                if self.dashboard:
                    self.dashboard.add_ad()

        elif action == "anti_silence" and self.anti_silence:
            action = self.anti_silence.get_action()
            if action:
                await self._announce(action.message)
                if self.dashboard:
                    self.dashboard.add_silence_intervention()

    async def _announce(self, message: str) -> None:
        """Announce a message through the platform."""
        logger.info("Director announce: %s", message[:80])
        # Publish through stream
        if self.platform_gateway:
            for conn in self.platform_gateway._connectors.values():
                await conn.send_message(message)

    # ── External Event Input ──────────────────────────────────

    def on_user_interaction(self) -> None:
        """Called whenever a user interacts (danmu, like, gift, follow)."""
        self._last_user_interaction = time.time()

    async def on_danmu(self, danmu) -> None:
        """Process incoming danmu through the director."""
        self.on_user_interaction()

        if self.danmu_center:
            processed = await self.danmu_center.process(danmu)
            if processed:
                if self.dashboard:
                    self.dashboard.add_comment()

                # Check if it's a stock question
                if self.stock_qa:
                    answer = await self.stock_qa.answer(processed)
                    if answer and answer.answer_type != "greeting":
                        self._intervention_queue.put_nowait(DirectorDecision(
                            phase=self._phase,
                            next_action="stock_qa",
                            action_data=answer.to_dict(),
                            priority=ContentPriority.HIGH,
                            reason=f"Stock Q&A: {answer.stock_name}",
                        ))
                        if self.dashboard:
                            self.dashboard.add_qa()

    async def on_gift_event(self, event: GiftEvent) -> None:
        """Process a gift event."""
        self.on_user_interaction()

        # Push as intervention for high-value gifts
        if event.gift_level == GiftLevel.SUPER or event.gift_value >= 100:
            self._intervention_queue.put_nowait(DirectorDecision(
                phase=self._phase,
                next_action="gift_thanks",
                action_data={
                    "username": event.username,
                    "gift_name": event.gift_name,
                    "gift_value": event.gift_value,
                    "gift_level": event.gift_level,
                    "platform": event.platform.value,
                },
                priority=ContentPriority.CRITICAL,
                reason=f"Super gift from {event.username}: {event.gift_name}",
            ))

        # Process through gift agent
        if self.gift:
            interaction = self.gift.on_gift(
                username=event.username,
                gift_name=event.gift_name,
                gift_value=event.gift_value,
                gift_level=event.gift_level,
            )
            if interaction and event.gift_level != GiftLevel.SUPER:
                await self._announce(interaction.message)

        if self.dashboard:
            self.dashboard.add_gift(event.gift_count, event.gift_value)

        # Evaluate clip-worthiness
        if self.clip_gen:
            clip = self.clip_gen.evaluate_moment(gift_value=event.gift_value)
            if clip:
                logger.info("Clip triggered by gift: %s", clip.clip_id)
                if self.dashboard:
                    self.dashboard.add_clip()

    async def on_like_event(self, event: LikeEvent) -> None:
        """Process a like event."""
        self.on_user_interaction()

        if self.engagement:
            action = self.engagement.on_like(
                username=event.username,
                count=event.count,
                total_likes=event.total_likes,
                platform=event.platform.value,
            )
            if action:
                await self._announce(action.message)

        if self.dashboard:
            self.dashboard.add_likes(event.count)

        # Clip evaluation
        if self.clip_gen:
            clip = self.clip_gen.evaluate_moment(like_count=event.total_likes)
            if clip:
                logger.info("Clip triggered by likes: %s", clip.clip_id)

    async def on_follow_event(self, event: FollowEvent) -> None:
        """Process a follow/unfollow event."""
        self.on_user_interaction()

        if self.fan_tracker:
            self.fan_tracker.update(
                username=event.username,
                event_type=event.event_type.value,
                follower_count=event.follower_count,
                platform=event.platform.value,
            )

        if self.dashboard:
            if event.event_type.value == "follow":
                self.dashboard.add_follow()
            else:
                self.dashboard.add_unfollow()

    async def on_viewer_event(self, event: ViewerEvent) -> None:
        """Process viewer count update."""
        if self.dashboard:
            self.dashboard.update_viewers(event.viewer_count)

    # ── Operation evaluation ──────────────────────────────────

    def evaluate_operation(self) -> None:
        """Periodic operation evaluation — called externally or via timer."""
        if not self.dashboard or not self.operation:
            return

        dashboard = self.dashboard
        advice = self.operation.evaluate(
            danmu_per_minute=dashboard.danmu_rate,
            viewer_count=dashboard.current_viewers,
            like_per_minute=dashboard.like_rate,
            gift_per_minute=dashboard.gift_rate,
        )

        if advice:
            self._intervention_queue.put_nowait(DirectorDecision(
                phase=self._phase,
                next_action="operation_advice",
                action_data=advice.to_dict(),
                priority=ContentPriority.HIGH,
                reason=advice.reason,
            ))

    # ── Stats ─────────────────────────────────────────────────

    def get_rundown(self) -> dict:
        """Get current show rundown/status."""
        now = time.time()
        return {
            "phase": self._phase.value,
            "uptime_seconds": now - self._started_at if self._started_at else 0,
            "decision_count": self._decision_count,
            "interventions_pending": self._intervention_queue.qsize(),
            "last_decisions": [
                d.to_dict() for d in list(self._decision_log)[-10:]
            ],
            "next_segments": {
                "stock_analysis_in": max(0, self.config.stock_analysis_interval - (now - self._last_stock_analysis)),
                "hot_sector_in": max(0, self.config.hot_sector_interval - (now - self._last_hot_sector)),
                "traffic_cta_in": max(0, self.config.traffic_cta_interval - (now - self._last_traffic_cta)),
            },
            "silence_seconds": now - self._last_user_interaction,
        }
