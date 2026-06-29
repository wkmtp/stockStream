"""Engagement agent — auto-interact based on viewer likes.

Rules:
- Like count >= 10: Thank the viewer
- Like count >= 100: Trigger interaction animation
- Like count >= 1000: Trigger special thanks

Generates natural host interaction content.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class LikeThreshold(Enum):
    SMALL = 10        # 感谢
    MEDIUM = 100      # 互动动画
    LARGE = 1000      # 特别感谢
    MASSIVE = 10000   # 大事感谢


@dataclass()
class EngagementAction:
    """An engagement action triggered by likes."""
    username: str
    platform: str
    total_likes: int
    threshold: LikeThreshold
    action_type: str           # "thanks" | "animation" | "special"
    message: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "platform": self.platform,
            "total_likes": self.total_likes,
            "threshold": self.threshold.name,
            "action_type": self.action_type,
            "message": self.message,
            "timestamp": self.timestamp,
        }


# ── Thank-you templates ──────────────────────────────────────────

THANKS_TEMPLATES: dict[LikeThreshold, list[str]] = {
    LikeThreshold.SMALL: [
        "感谢{user}的点赞支持！",
        "{user}点赞了，谢谢支持！你的关注是我们的动力！",
        "谢谢{user}的点赞！喜欢我们分析的朋友记得点个关注~",
        "感谢{user}老铁的点赞！",
    ],
    LikeThreshold.MEDIUM: [
        "哇！{user}给我们点了一百个赞！太有牌面了！谢谢支持！",
        "感谢{user}的大量点赞！小财妹太开心了~老张你觉得呢？",
        "{user}老板大气！一百个赞！必须请你喝杯茶！",
    ],
    LikeThreshold.LARGE: [
        "天哪！{user}给我们点了一千个赞！全场起立！谢谢老板！",
        "谢谢{user}千赞支持！这就是真爱啊！老张咱们是不是该表示一下？",
        "{user}千赞大佬来了！小财妹代表直播间感谢您的厚爱！",
    ],
    LikeThreshold.MASSIVE: [
        "🎉🎉🎉 {user}一万赞！老张你看看！这才是真爱啊！谢谢老板！全体起立！",
        "哇！一万赞！{user}老板太豪了！直播间第一土豪诞生！谢谢支持！",
    ],
}


class EngagementAgent:
    """Monitor likes and generate interaction responses.

    Usage::

        agent = EngagementAgent()
        action = agent.on_like("张三", 10, 100)
        if action:
            await host_say(action.message)
    """

    def __init__(self, cooldown_seconds: float = 3.0) -> None:
        self.cooldown_seconds = cooldown_seconds
        self._last_action_time: float = 0.0
        self._total_likes: dict[str, int] = {}          # platform -> total
        self._user_likes: dict[str, int] = {}            # user -> total
        self._thanked_users: set[str] = set()
        self._action_history: list[EngagementAction] = []
        self._triggered_thresholds: set[str] = set()     # "user:threshold"

    def on_like(
        self, username: str, count: int, total_likes: int,
        platform: str = "unknown",
    ) -> EngagementAction | None:
        """Process a like event, return an action if threshold triggered."""

        if not username:
            return None

        # Cooldown
        now = time.time()
        if now - self._last_action_time < self.cooldown_seconds:
            return None

        # Track totals
        self._total_likes[platform] = self._total_likes.get(platform, 0) + count
        self._user_likes[username] = self._user_likes.get(username, 0) + count

        user_total = self._user_likes[username]

        # Check thresholds
        threshold = None
        for t in [LikeThreshold.MASSIVE, LikeThreshold.LARGE, LikeThreshold.MEDIUM, LikeThreshold.SMALL]:
            if user_total >= t.value:
                trigger_key = f"{username}:{t.name}"
                if trigger_key not in self._triggered_thresholds:
                    threshold = t
                    self._triggered_thresholds.add(trigger_key)
                    break

        if threshold is None:
            return None

        # Generate action
        if threshold == LikeThreshold.SMALL:
            action_type = "thanks"
        elif threshold == LikeThreshold.MEDIUM:
            action_type = "animation"
        else:
            action_type = "special"

        templates = THANKS_TEMPLATES.get(threshold, THANKS_TEMPLATES[LikeThreshold.SMALL])
        message = random.choice(templates).format(user=username)

        action = EngagementAction(
            username=username,
            platform=platform,
            total_likes=user_total,
            threshold=threshold,
            action_type=action_type,
            message=message,
            timestamp=now,
        )

        self._last_action_time = now
        self._action_history.append(action)
        if len(self._action_history) > 500:
            self._action_history = self._action_history[-200:]

        logger.info("Engagement: %s %s (user=%s, likes=%d)",
                     action_type, threshold.name, username, user_total)

        return action

    def get_stats(self) -> dict:
        return {
            "total_likes": self._total_likes,
            "top_users": sorted(
                self._user_likes.items(), key=lambda x: x[1], reverse=True
            )[:10],
            "recent_actions": [
                a.to_dict() for a in self._action_history[-10:]
            ],
        }
