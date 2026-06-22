"""事件总线 — 发布/订阅模式，模块间零耦合通讯。

架构原则：
    1. 模块间禁止直接调用，全部通过事件总线通讯
    2. 支持异步事件处理
    3. 事件类型化，保证类型安全
    4. 支持通配符订阅和优先级
    5. 内置事件追踪和度量

使用方式:
    from src.core.event_bus import EventBus, Event

    bus = EventBus()

    @bus.on("market.price_updated")
    async def on_price(event: Event):
        print(f"Price: {event.data}")

    await bus.emit("market.price_updated", {"symbol": "600519", "price": 1800.0})
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


# ── Event Type Definitions ────────────────────────────────────────────


class EventCategory(Enum):
    """事件大类，用于分组和监控。"""
    MARKET = "market"           # 行情数据
    DANMU = "danmu"             # 弹幕评论
    GIFT = "gift"               # 礼物
    LIKE = "like"               # 点赞
    FOLLOW = "follow"           # 关注
    TTS = "tts"                 # 语音合成
    STREAM = "stream"           # 推流
    SCENE = "scene"             # 场景切换
    SELECTOR = "selector"       # 选股
    ANALYSIS = "analysis"       # AI 分析
    TRADING = "trading"         # 交易
    AVATAR = "avatar"           # 数字人
    SYSTEM = "system"           # 系统事件
    LIVE = "live"               # 直播运营
    DASHBOARD = "dashboard"     # 仪表盘
    CLIP = "clip"               # 短视频切片


@dataclass
class Event:
    """统一事件结构。"""

    type: str                          # 事件类型，如 "market.price_updated"
    data: Any = None                   # 事件载荷
    source: str = ""                   # 事件来源模块
    timestamp: float = field(default_factory=time.time)
    id: str = ""                       # 事件唯一ID
    correlation_id: str = ""           # 关联ID（用于追踪事件链）
    priority: int = 0                  # 优先级（越大越高）

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "data": self.data,
            "source": self.source,
            "timestamp": self.timestamp,
            "id": self.id,
            "correlation_id": self.correlation_id,
            "priority": self.priority,
        }

    def category(self) -> EventCategory:
        """从事件类型推断大类。"""
        prefix = self.type.split(".")[0]
        try:
            return EventCategory(prefix)
        except ValueError:
            return EventCategory.SYSTEM


# ── Subscriber ─────────────────────────────────────────────────────────


@dataclass
class _Subscriber:
    """内部订阅记录。"""
    callback: Callable[[Event], Coroutine[Any, Any, None]]
    pattern: str
    priority: int = 0
    once: bool = False


# ── Event Bus ──────────────────────────────────────────────────────────


class EventBus:
    """全局事件总线 — 发布/订阅模式核心。

    特性:
        - 异步事件发布
        - 通配符订阅 (market.* 匹配 market 下所有事件)
        - 优先级排序 (priority 越大越先执行)
        - 一次性订阅 (once=True)
        - 事件历史记录
        - 性能度量
    """

    def __init__(self, max_history: int = 1000) -> None:
        self._subscribers: dict[str, list[_Subscriber]] = defaultdict(list)
        self._history: list[Event] = []
        self._max_history = max_history
        self._stats = EventStats()
        self._lock = asyncio.Lock()
        self._running = False
        self._pending_tasks: set[asyncio.Task] = set()
        self._max_pending_tasks = 200  # 24h 稳定性：限制并发 emit_async 任务数

    # ── Subscribe ──────────────────────────────────────────────────

    def on(
        self,
        pattern: str,
        priority: int = 0,
        once: bool = False,
    ) -> Callable:
        """装饰器方式订阅事件。

        Args:
            pattern: 事件类型模式，支持 * 通配符。如 "market.*" 匹配所有 market 事件
            priority: 优先级，越大越先执行
            once: 是否仅触发一次

        Usage:
            @bus.on("market.price_updated")
            async def handle(event): ...
        """
        def decorator(func: Callable[[Event], Coroutine[Any, Any, None]]):
            sub = _Subscriber(callback=func, pattern=pattern, priority=priority, once=once)
            self._subscribers[pattern].append(sub)
            self._subscribers[pattern].sort(key=lambda s: -s.priority)
            return func
        return decorator

    def subscribe(
        self,
        pattern: str,
        callback: Callable[[Event], Coroutine[Any, Any, None]],
        priority: int = 0,
        once: bool = False,
    ) -> None:
        """编程方式订阅事件。"""
        sub = _Subscriber(callback=callback, pattern=pattern, priority=priority, once=once)
        self._subscribers[pattern].append(sub)
        self._subscribers[pattern].sort(key=lambda s: -s.priority)

    def unsubscribe(
        self,
        pattern: str,
        callback: Callable[[Event], Coroutine[Any, Any, None]],
    ) -> None:
        """取消订阅。"""
        if pattern in self._subscribers:
            self._subscribers[pattern] = [
                s for s in self._subscribers[pattern] if s.callback is not callback
            ]

    # ── Emit ───────────────────────────────────────────────────────

    async def emit(
        self,
        event_type: str,
        data: Any = None,
        source: str = "",
        priority: int = 0,
        correlation_id: str = "",
    ) -> None:
        """同步发布事件（等待所有订阅者处理完毕）。

        Args:
            event_type: 事件类型，如 "market.price_updated"
            data: 事件载荷
            source: 事件来源模块名
            priority: 优先级
            correlation_id: 关联ID
        """
        event = Event(
            type=event_type,
            data=data,
            source=source,
            priority=priority,
            correlation_id=correlation_id,
            id=f"{event_type}_{int(time.time() * 1_000_000)}",
        )

        # 记录历史
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        self._stats.total_events += 1

        # 收集匹配的订阅者
        matched = await self._match_subscribers(event_type)

        if not matched:
            self._stats.unmatched += 1
            return

        self._stats.delivered += len(matched)

        # 按优先级执行
        to_remove: list[tuple[str, _Subscriber]] = []
        for sub in matched:
            try:
                await sub.callback(event)
                if sub.once:
                    to_remove.append((sub.pattern, sub))
            except Exception as exc:
                self._stats.errors += 1
                logger.error(
                    "Event handler error: type=%s handler=%s: %s",
                    event_type, sub.callback.__name__, exc,
                )

        # 清理一次性订阅
        async with self._lock:
            for pattern, sub in to_remove:
                if pattern in self._subscribers and sub in self._subscribers[pattern]:
                    self._subscribers[pattern].remove(sub)

    async def emit_async(
        self,
        event_type: str,
        data: Any = None,
        source: str = "",
        priority: int = 0,
        correlation_id: str = "",
    ) -> None:
        """异步发布事件（不等待订阅者处理完毕，fire-and-forget）。

        24h 稳定性：限制并发 fire-and-forget 任务数，防止 Task 泄漏。
        """
        # 清理已完成的任务
        self._pending_tasks = {t for t in self._pending_tasks if not t.done()}
        if len(self._pending_tasks) >= self._max_pending_tasks:
            logger.warning("EventBus: emit_async task limit reached (%d), dropping event %s",
                          self._max_pending_tasks, event_type)
            return
        task = asyncio.create_task(self.emit(event_type, data, source, priority, correlation_id))
        self._pending_tasks.add(task)

    # ── Query ──────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """获取事件总线统计。"""
        return {
            "total_events": self._stats.total_events,
            "delivered": self._stats.delivered,
            "unmatched": self._stats.unmatched,
            "errors": self._stats.errors,
            "history_size": len(self._history),
            "subscriber_count": sum(len(v) for v in self._subscribers.values()),
        }

    def get_history(self, event_type: str = "", limit: int = 50) -> list[Event]:
        """查询事件历史。"""
        if event_type:
            return [e for e in self._history if e.type.startswith(event_type)][-limit:]
        return self._history[-limit:]

    def subscriber_count(self) -> dict[str, int]:
        """返回各模式的订阅数量。"""
        return {k: len(v) for k, v in self._subscribers.items() if v}

    # ── Lifecycle ──────────────────────────────────────────────────

    def clear(self) -> None:
        """清空所有订阅和历史。"""
        self._subscribers.clear()
        self._history.clear()
        self._stats = EventStats()
        for t in list(self._pending_tasks):
            if not t.done():
                t.cancel()
        self._pending_tasks.clear()

    # ── Internal ───────────────────────────────────────────────────

    async def _match_subscribers(self, event_type: str) -> list[_Subscriber]:
        """匹配所有订阅者。

        匹配规则:
            1. 精确匹配: "market.price" 匹配 "market.price"
            2. 前缀通配: "market.*" 匹配 "market.price", "market.volume" 等
            3. 全通配: "*" 匹配所有事件
        """
        matched: list[_Subscriber] = []
        async with self._lock:
            for pattern, subs in self._subscribers.items():
                if self._match_pattern(pattern, event_type):
                    matched.extend(subs)
        # 去重并按优先级排序
        seen = set()
        unique = []
        for sub in sorted(matched, key=lambda s: -s.priority):
            if sub.callback not in seen:
                seen.add(sub.callback)
                unique.append(sub)
        return unique

    @staticmethod
    def _match_pattern(pattern: str, event_type: str) -> bool:
        """检查事件类型是否匹配模式。"""
        if pattern == "*":
            return True
        if pattern == event_type:
            return True
        if pattern.endswith(".*"):
            prefix = pattern[:-2]
            return event_type.startswith(prefix + ".")
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            return event_type.startswith(prefix)
        return False


# ── Event Stats ───────────────────────────────────────────────────────


@dataclass
class EventStats:
    total_events: int = 0
    delivered: int = 0
    unmatched: int = 0
    errors: int = 0


# ── Global singleton ──────────────────────────────────────────────────

_global_bus: EventBus | None = None
_lock = asyncio.Lock()


async def get_event_bus() -> EventBus:
    """获取全局事件总线单例。"""
    global _global_bus
    if _global_bus is None:
        async with _lock:
            if _global_bus is None:
                _global_bus = EventBus()
    return _global_bus


def reset_event_bus() -> None:
    """重置全局事件总线（用于测试）。"""
    global _global_bus
    if _global_bus:
        _global_bus.clear()
    _global_bus = None
