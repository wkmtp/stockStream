"""弹幕处理中心。"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from collections import deque

from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)

# ── 24h 稳定性：容量 & 清理常量 ──
_QUEUE_MAXLEN = 2000          # 弹幕队列最大保留条数
_SEEN_MAXSIZE = 10_000        # 去重集合最大容量
_SEEN_CLEANUP_INTERVAL = 300  # 去重集合清理间隔（秒）


@dataclass
class DanmuMessage:
    platform: str = ""
    username: str = ""
    content: str = ""
    level: int = 0
    priority: int = 0
    tags: list[str] = field(default_factory=list)
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "username": self.username,
            "content": self.content,
            "level": self.level,
            "priority": self.priority,
            "tags": self.tags,
        }


class DanmuCenter:
    """弹幕处理中心。

    监听事件:
      danmu.new → 接收并处理弹幕
    推送事件:
      danmu.processed  — 处理后弹幕
    """

    def __init__(self, bus: EventBus | None = None) -> None:
        self._bus: EventBus | None = bus
        self._queue: deque[DanmuMessage] = deque(maxlen=_QUEUE_MAXLEN)
        self._seen: set[str] = set()  # 去重（定期清理）
        self._last_seen_cleanup = time.time()
        self._spam_keywords = ["加微信", "免费推荐", "二维码", "私聊"]
        self._stock_keywords = ["怎么看", "还能涨", "该卖了", "能买"]

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    async def start(self) -> None:
        bus = await self.bus

        @bus.on("danmu.new")
        async def _on_danmu(event):
            await self._process(event)

        logger.info("DanmuCenter started")

    async def _process(self, event) -> None:
        data = event.data or {}
        content = data.get("content", "")
        username = data.get("username", "")
        platform = data.get("platform", "")

        # 定期清理去重集合，防止 24h 运行后内存膨胀
        now = time.time()
        if len(self._seen) >= _SEEN_MAXSIZE or (now - self._last_seen_cleanup) >= _SEEN_CLEANUP_INTERVAL:
            self._seen.clear()
            self._last_seen_cleanup = now
            logger.debug("DanmuCenter: cleaned dedup set (size was >= %d)", _SEEN_MAXSIZE)

        # 去重
        dedup_key = f"{username}:{content}"
        if dedup_key in self._seen:
            return
        self._seen.add(dedup_key)

        # 过滤广告
        if any(kw in content for kw in self._spam_keywords):
            return

        # 标签识别
        tags = []
        priority = 0
        if any(kw in content for kw in self._stock_keywords):
            tags.append("stock_question")
            priority = 10

        msg = DanmuMessage(
            platform=platform,
            username=username,
            content=content,
            level=data.get("user_level", 0),
            priority=priority,
            tags=tags,
        )
        self._queue.append(msg)

        bus = await self.bus
        if msg.tags:
            await bus.emit_async("danmu.processed", msg.to_dict(),
                                source="danmu_center")

    def drain_queue(self, max_count: int = 20) -> list[DanmuMessage]:
        items = []
        while self._queue and len(items) < max_count:
            items.append(self._queue.popleft())
        # 按优先级排序
        items.sort(key=lambda m: -m.priority)
        return items
