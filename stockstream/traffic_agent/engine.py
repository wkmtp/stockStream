"""Traffic agent — auto-generate follow-promotion messages.

Generates natural follow-CTAs during live stream:
- Every ~15 minutes
- Non-repetitive
- Multiple styles for variety
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass()
class TrafficAction:
    """A traffic-driving action (follow CTA)."""
    message: str
    action_type: str = "follow_cta"       # follow_cta | share_cta | like_cta
    priority: int = 3
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "message": self.message,
            "action_type": self.action_type,
            "priority": self.priority,
            "timestamp": self.timestamp,
        }


# ── Follow CTA Templates ────────────────────────────────────────

FOLLOW_CTA_TEMPLATES: list[str] = [
    "喜欢我们分析风格的朋友，动动手指点个关注，每天带你读懂A股！",
    "觉得有收获的老铁，给个关注支持一下，咱们一起在股市里赚钱！",
    "没点关注的朋友，右上角关注走一波，每天准时开播分析行情~",
    "新来的朋友记得点个关注，老张和小财妹每天都在这里等你！",
    "如果你想每天收到这样的分析，关注我们就是最好的支持！",
    "关注不迷路，每天直播带你把握市场节奏，手把手教你炒股！",
    "关注我们已经破十万了，还没关注的朋友抓紧上车！",
    "关注一下不吃亏，每天财经干货分享，还有不定时福利哦~",
    "投资是一场修行，关注我们，让专业分析成为你的导航！",
    "为什么你总是亏钱？关注我们，我告诉大家一个秘密…",
    "股市里最值钱的是什么？是信息差！关注我们，第一时间获取最新动态！",
    "你知道吗？80%的散户都在亏钱，关注我们，成为那20%的赢家！",
    "今天又有很多朋友赚钱了，你是下一个吗？关注我们，帮你找到答案！",
    "有多少人是每天准时来看我们直播的？来，扣个1，然后顺手点个关注！",
    "关注关注关注！重要的事情说三遍！关注了就不会错过好股票了！",
]

SHARE_CTA_TEMPLATES: list[str] = [
    "觉得今天分析干货很多？分享给你的股友，大家一起交流学习！",
    "好东西要分享，把这直播间转发给你身边炒股的朋友~",
    "今天的内容太精彩了，赶紧分享到你的炒股群，让大家也看看！",
]

LIKE_CTA_TEMPLATES: list[str] = [
    "动动你的小手点个赞，让更多人看到我们的专业分析！",
    "点赞破万，老张今天加餐讲干货！",
    "直播间的小伙伴们，点点赞冲一冲，让更多人看到我们！",
]


class TrafficAgent:
    """Auto-generate traffic-driving messages at intervals.

    Usage::

        traffic = TrafficAgent(interval_minutes=15)
        action = traffic.should_trigger()
        if action:
            await host_say(action.message)
    """

    def __init__(self, interval_minutes: int = 15) -> None:
        self.interval_seconds = interval_minutes * 60
        self._last_cta_time: float = time.time()  # Don't trigger immediately
        self._used_templates: list[int] = []
        self._total_ctas = 0
        self._action_history: list[TrafficAction] = []
        self._action_history_max: int = 200  # V3.0: 防止无界增长

    def should_trigger(self) -> TrafficAction | None:
        """Check if it's time to send a traffic CTA."""
        now = time.time()
        if now - self._last_cta_time < self.interval_seconds:
            return None

        # Pick a non-recent template
        template = self._pick_template()
        action_type = "follow_cta"

        # Occasionally mix in share/like CTAs (20% chance)
        if random.random() < 0.15:
            template = random.choice(SHARE_CTA_TEMPLATES)
            action_type = "share_cta"
        elif random.random() < 0.1:
            template = random.choice(LIKE_CTA_TEMPLATES)
            action_type = "like_cta"

        action = TrafficAction(
            message=template,
            action_type=action_type,
            timestamp=now,
        )

        self._last_cta_time = now
        self._total_ctas += 1
        self._action_history.append(action)
        # V3.0: 防止无界增长，保留最近 100 条
        if len(self._action_history) > self._action_history_max:
            self._action_history = self._action_history[-100:]
        logger.debug("Traffic: %s triggered (total=%d)", action_type, self._total_ctas)
        return action

    def _pick_template(self) -> str:
        """Pick a template avoiding recent ones."""
        available = [i for i in range(len(FOLLOW_CTA_TEMPLATES)) if i not in self._used_templates[-5:]]
        if not available:
            available = list(range(len(FOLLOW_CTA_TEMPLATES)))

        idx = random.choice(available)
        self._used_templates.append(idx)
        # Keep history bounded
        if len(self._used_templates) > 50:
            self._used_templates = self._used_templates[-20:]
        return FOLLOW_CTA_TEMPLATES[idx]

    def force_trigger(self) -> TrafficAction:
        """Force a traffic CTA regardless of timing."""
        template = random.choice(FOLLOW_CTA_TEMPLATES)
        action = TrafficAction(message=template, action_type="follow_cta")
        self._action_history.append(action)
        self._total_ctas += 1
        return action

    def get_stats(self) -> dict:
        return {
            "total_ctas": self._total_ctas,
            "interval_minutes": self.interval_seconds / 60,
            "last_cta_time": self._last_cta_time,
        }
