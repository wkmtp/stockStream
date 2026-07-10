"""Director agent — controls live show pacing and segment scheduling.

Acts as a "TV director" that decides what content plays when, ensuring
the show flows naturally with varied segment types at proper intervals.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Callable, Awaitable

from stockstream.dual_host.models import (
    DialogueScript,
    DualHostConfig,
    ScheduleSlot,
    ShowSegmentType,
)

logger = logging.getLogger(__name__)

# Callback type for when a new segment is scheduled
SegmentCallback = Callable[[ShowSegmentType, dict], Awaitable[DialogueScript | None]]


class DirectorAgent:
    """Manages show rundown and triggers segments on schedule.

    Features:
    - Tracks elapsed time and fires segments at configured intervals
    - Priority-based scheduling — higher priority segments preempt lower
    - Segment deduplication — won't fire same segment twice within cooldown
    """

    def __init__(self, config: DualHostConfig | None = None) -> None:
        self.config = config or DualHostConfig()
        self._started_at: float = 0.0
        self._last_fired: dict[ShowSegmentType, float] = {}
        self._running = False
        self._tick_task: asyncio.Task[None] | None = None
        self._on_segment: SegmentCallback | None = None
        self._segment_count: int = 0
        self._fire_tasks: dict[str, asyncio.Task] = {}  # 24h: 追踪 fire-and-forget tasks

    def on_segment(self, callback: SegmentCallback) -> None:
        """Register callback invoked when a segment triggers."""
        self._on_segment = callback

    # ── lifecycle ───────────────────────────────────────────────

    async def start(self) -> None:
        """Start the director loop."""
        self._started_at = time.monotonic()
        self._running = True
        self._segment_count = 0
        self._tick_task = asyncio.create_task(self._tick_loop())
        logger.info("DirectorAgent started (schedule=%d slots)", len(self.config.schedule))

    async def stop(self) -> None:
        """Stop the director loop."""
        self._running = False
        if self._tick_task and not self._tick_task.done():
            self._tick_task.cancel()
            try:
                await self._tick_task
            except asyncio.CancelledError:
                pass
        # 24h: 取消所有 fire-and-forget tasks
        for name, t in list(self._fire_tasks.items()):
            if not t.done():
                t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._fire_tasks.clear()
        logger.info("DirectorAgent stopped (segments=%d)", self._segment_count)

    # ── helpers ─────────────────────────────────────────────────

    @property
    def elapsed_sec(self) -> float:
        """Seconds since the show started."""
        if not self._started_at:
            return 0.0
        return time.monotonic() - self._started_at

    @property
    def elapsed_min(self) -> float:
        return self.elapsed_sec / 60.0

    def get_rundown(self) -> list[dict]:
        """Return the current show schedule status."""
        now = time.monotonic()
        return [
            {
                "segment_type": s.segment_type.value,
                "interval_min": s.interval_minutes,
                "priority": s.priority,
                "last_fired_sec": now - self._last_fired.get(s.segment_type, 0),
                "next_in_sec": max(0, s.interval_minutes * 60 - (now - self._last_fired.get(s.segment_type, self._started_at))),
            }
            for s in self.config.schedule
        ]

    # ── internal ────────────────────────────────────────────────

    async def _tick_loop(self) -> None:
        """Main scheduling loop — ticks every second."""
        # Fire opening immediately
        await self._fire_segment(ShowSegmentType.OPENING)

        while self._running:
            try:
                await asyncio.sleep(self.config.tick_seconds)
            except asyncio.CancelledError:
                break

            await self._check_schedule()

    async def _check_schedule(self) -> None:
        """Check all schedule slots and fire due segments."""
        now = time.monotonic()

        # Sort by priority (lower = higher priority)
        due_slots: list[ScheduleSlot] = []
        for slot in self.config.schedule:
            last = self._last_fired.get(slot.segment_type, self._started_at)
            elapsed_since_last = now - last
            if elapsed_since_last >= slot.interval_minutes * 60:
                due_slots.append(slot)

        if not due_slots:
            return

        # Fire highest priority slot
        due_slots.sort(key=lambda s: s.priority)
        await self._fire_segment(due_slots[0].segment_type)

    async def _fire_segment(self, segment_type: ShowSegmentType) -> None:
        """Trigger a segment callback."""
        self._last_fired[segment_type] = time.monotonic()
        self._segment_count += 1

        logger.info("Director triggers: %s (elapsed=%.1f min)",
                     segment_type.value, self.elapsed_min)

        if self._on_segment:
            try:
                result = await self._on_segment(segment_type, {
                    "elapsed_sec": self.elapsed_sec,
                    "segment_seq": self._segment_count,
                })
                if result:
                    logger.debug("Segment produced %d turns", len(result.turns))
            except Exception as exc:
                logger.error("Segment callback failed for %s: %s", segment_type, exc)

    def request_segment(self, segment_type: ShowSegmentType,
                        context: dict | None = None) -> None:
        """Manually request a segment (for audience Q&A triggers)."""
        # 24h: fire-and-forget task 加入追踪，防止异常被忽略
        task = asyncio.create_task(self._fire_segment(segment_type))
        self._fire_tasks[task.get_name()] = task
