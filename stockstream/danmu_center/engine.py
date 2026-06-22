"""Danmu center — unified comment processing pipeline.

Input: Raw danmu events from Douyin and Kuaishou connectors.
Output: Filtered, deduplicated, enriched danmu events.

Features:
- Ad/spam filtering
- Duplicate removal
- Keyword recognition
- Priority ranking
- Platform unification
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from stockstream.platform_gateway.common.models import CommentEvent, Platform

logger = logging.getLogger(__name__)


# ── Danmu Models ─────────────────────────────────────────────────

class DanmuPriority(int, Enum):
    LOW = 0         # 普通弹幕
    NORMAL = 1      # 一般互动
    HIGH = 2        # 提问弹幕
    URGENT = 3      # 高价值弹幕（礼物附带、大V）


class DanmuTag(str, Enum):
    QUESTION = "question"         # 提问类
    STOCK_MENTION = "stock"       # 提及股票
    PRAISE = "praise"             # 赞美
    COMPLAINT = "complaint"       # 吐槽
    GREETING = "greeting"         # 打招呼
    SPAM = "spam"                 # 广告/垃圾
    NORMAL = "normal"             # 普通


@dataclass(slots=True)
class DanmuMessage:
    """Unified danmu message after processing."""
    platform: Platform
    username: str
    content: str
    user_level: int = 0
    priority: DanmuPriority = DanmuPriority.NORMAL
    tags: list[DanmuTag] = field(default_factory=list)
    matched_stocks: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    event_id: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "platform": self.platform.value,
            "user": self.username,
            "content": self.content,
            "level": self.user_level,
            "priority": self.priority.name,
            "tags": [t.value for t in self.tags],
            "matched_stocks": self.matched_stocks,
            "timestamp": self.timestamp,
            "event_id": self.event_id,
        }


# ── Spam Patterns ────────────────────────────────────────────────

SPAM_PATTERNS: list[str] = [
    r"\b(vx|wx|weixin|微信)\s*[：:]\s*\w{5,}",
    r"\b(加微信|加V)\b",
    r"\b(qq|扣扣)\s*[：:]\s*\d{5,}",
    r"\b(免费荐股|免费带单|稳赚不赔|内幕消息)\b",
    r"\b(点击链接|http|www\.)\b",
    r"\b(加群|入群|进群)\b",
    r"(\+V|\+v|\+微信|\+QQ)",
    r"\b(\d{8,})\b",  # long number strings in isolation
    r"(加.*[老师|助理|大师])",
]

# ── Question Patterns ────────────────────────────────────────────

QUESTION_PATTERNS: list[str] = [
    r".*(怎么看|还能拿吗|还会涨吗|还会跌吗|能买吗|能卖吗).*",
    r".*(什么时候.*买|什么时候.*卖|能不能.*入).*",
    r".*(分析一下|点评一下|讲一下|说一下).*",
    r".*(推荐.*股票|推荐.*板块|推荐.*基金).*",
    r".*[？?]$",
]

# ── Praise Patterns ──────────────────────────────────────────────

PRAISE_PATTERNS: list[str] = [
    r".*(讲得好|分析到位|感谢|谢谢|厉害|牛|666|学到了).*",
    r".*(关注了|支持|加油|很棒|优秀|专业).*",
]

# ── Greeting Patterns ────────────────────────────────────────────

GREETING_PATTERNS: list[str] = [
    r".*(大家好|来了|打卡|早上好|下午好|晚上好|早安|晚安).*",
    r"^(大家好|来了来了|打卡).*",
]

# ── Stock mention patterns ───────────────────────────────────────

STOCK_PATTERNS = [
    re.compile(p) for p in [
        r"(贵州茅台|茅台)",
        r"(宁德时代|宁德)",
        r"(比亚迪)",
        r"(五粮液)",
        r"(招商银行|招行)",
        r"(平安保险|平安)",
        r"(美的集团|美的)",
        r"(格力电器|格力)",
        r"(隆基绿能|隆基)",
        r"(中芯国际|中芯)",
        r"(海康威视|海康)",
        r"(中兴通讯|中兴)",
        r"(\d{6})",  # stock code
    ]
]

KNOWN_STOCKS: dict[str, str] = {
    "茅台": "600519",
    "贵州茅台": "600519",
    "宁德": "300750",
    "宁德时代": "300750",
    "比亚迪": "002594",
    "五粮液": "000858",
    "招行": "600036",
    "招商银行": "600036",
    "平安": "601318",
    "美的": "000333",
    "格力": "000651",
    "隆基": "601012",
    "中芯": "688981",
    "海康": "002415",
    "中兴": "000063",
}


class DanmuCenter:
    """Central danmu processing pipeline.

    Processes raw comment events from all platforms and outputs
    clean, deduplicated, ranked danmu messages.
    """

    def __init__(
        self,
        dedup_window: int = 60,
        spam_threshold: int = 3,
        queue_size: int = 500,
    ) -> None:
        self.dedup_window = dedup_window        # seconds
        self.spam_threshold = spam_threshold
        self._output: asyncio.Queue[DanmuMessage] = asyncio.Queue(maxsize=queue_size)
        self._recent: OrderedDict[str, float] = OrderedDict()
        self._spam_counters: dict[str, int] = defaultdict(int)
        self._total_processed = 0
        self._total_filtered = 0
        self._total_spam = 0
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info("DanmuCenter started")

    async def stop(self) -> None:
        self._running = False
        logger.info("DanmuCenter stopped (processed=%d, filtered=%d, spam=%d)",
                     self._total_processed, self._total_filtered, self._total_spam)

    async def process(self, event: CommentEvent) -> DanmuMessage | None:
        """Process a raw comment event into a clean danmu message."""
        self._total_processed += 1

        content = event.content.strip()
        if not content:
            self._total_filtered += 1
            return None

        # 1. Spam detection
        if self._is_spam(content, event.username):
            self._total_spam += 1
            self._total_filtered += 1
            return None

        # 2. Deduplication
        dedup_key = f"{event.platform.value}:{event.username}:{content}"
        now = time.time()
        if dedup_key in self._recent:
            last_time = self._recent[dedup_key]
            if now - last_time < self.dedup_window:
                self._total_filtered += 1
                return None

        # Clean old entries
        self._recent[dedup_key] = now
        while self._recent and next(iter(self._recent.values())) < now - self.dedup_window * 2:
            self._recent.popitem(last=False)

        # 3. Tag classification
        tags = self._classify(content)
        if DanmuTag.SPAM in tags:
            self._total_spam += 1
            self._total_filtered += 1
            return None

        # 4. Stock extraction
        stocks = self._extract_stocks(content)

        # 5. Priority ranking
        priority = self._rank_priority(content, tags, event.user_level, stocks)

        msg = DanmuMessage(
            platform=event.platform,
            username=event.username,
            content=content,
            user_level=event.user_level,
            priority=priority,
            tags=tags,
            matched_stocks=stocks,
            timestamp=event.timestamp,
            event_id=event.event_id,
            raw=event.raw,
        )

        await self._output.put(msg)
        return msg

    async def get_next(self) -> DanmuMessage | None:
        """Get the next processed danmu message."""
        try:
            return await asyncio.wait_for(self._output.get(), timeout=1.0)
        except asyncio.TimeoutError:
            return None

    async def drain_all(self) -> list[DanmuMessage]:
        """Drain all pending messages, sorted by priority."""
        messages: list[DanmuMessage] = []
        while not self._output.empty():
            try:
                messages.append(self._output.get_nowait())
            except asyncio.QueueEmpty:
                break
        # Sort: urgent first, then high, normal, low
        messages.sort(key=lambda m: m.priority.value, reverse=True)
        return messages

    # ── Detection helpers ─────────────────────────────────────

    def _is_spam(self, content: str, username: str) -> bool:
        key = f"{username}:{content[:50]}"
        self._spam_counters[key] += 1
        if self._spam_counters[key] > self.spam_threshold:
            return True

        for pattern in SPAM_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                return True

        # Clean up old counters
        if len(self._spam_counters) > 10000:
            self._spam_counters.clear()

        return False

    def _classify(self, content: str) -> list[DanmuTag]:
        tags: list[DanmuTag] = []

        if any(re.match(p, content, re.IGNORECASE) for p in QUESTION_PATTERNS):
            tags.append(DanmuTag.QUESTION)

        if any(re.search(p, content) for p in STOCK_PATTERNS):
            tags.append(DanmuTag.STOCK_MENTION)

        if any(re.match(p, content, re.IGNORECASE) for p in PRAISE_PATTERNS):
            tags.append(DanmuTag.PRAISE)

        if any(re.match(p, content, re.IGNORECASE) for p in GREETING_PATTERNS):
            tags.append(DanmuTag.GREETING)

        if not tags:
            tags.append(DanmuTag.NORMAL)

        return tags

    def _extract_stocks(self, content: str) -> list[str]:
        stocks: list[str] = []
        seen: set[str] = set()

        for pattern in STOCK_PATTERNS:
            match = pattern.search(content)
            if match:
                raw = match.group(1)
                code = KNOWN_STOCKS.get(raw, raw)
                if code not in seen:
                    stocks.append(code)
                    seen.add(code)

        return stocks

    def _rank_priority(
        self, content: str, tags: list[DanmuTag], user_level: int, stocks: list[str]
    ) -> DanmuPriority:
        score = 0

        if DanmuTag.QUESTION in tags and stocks:
            score += 3   # stock question → URGENT
        elif DanmuTag.QUESTION in tags:
            score += 2
        elif stocks:
            score += 1

        if user_level > 20:
            score += 1
        if DanmuTag.STOCK_MENTION in tags:
            score += 1

        if score >= 3:
            return DanmuPriority.URGENT
        if score >= 2:
            return DanmuPriority.HIGH
        if score >= 1:
            return DanmuPriority.NORMAL
        return DanmuPriority.LOW

    def get_stats(self) -> dict:
        return {
            "total_processed": self._total_processed,
            "total_filtered": self._total_filtered,
            "total_spam": self._total_spam,
            "pending_messages": self._output.qsize(),
            "running": self._running,
        }
