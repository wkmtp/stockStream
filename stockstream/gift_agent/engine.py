"""Gift interaction agent — respond to viewer gift events.

Monitors gift events and generates appropriate thank-you messages
based on gift level (normal / premium / super).

Features:
- Gift level-based thank-you variations
- Digital human expression animation triggers
- Top donor tracking
- Cumulative gift value tracking
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from stockstream.platform_gateway.common.models import GiftLevel

logger = logging.getLogger(__name__)


class GiftResponseType(str, Enum):
    THANKS = "thanks"                   # 口头感谢
    ANIMATION = "animation"              # 触发动画
    SPECIAL = "special"                 # 特别感谢
    TOP_DONOR = "top_donor"             # 上榜感谢


@dataclass()
class GiftInteraction:
    """A gift interaction response."""
    username: str
    platform: str
    gift_name: str
    gift_value: float
    gift_level: GiftLevel
    total_value: float
    response_type: GiftResponseType
    message: str
    animation: str | None = None        # 数字人动作名
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "platform": self.platform,
            "gift_name": self.gift_name,
            "gift_value": self.gift_value,
            "gift_level": self.gift_level.value,
            "total_value": self.total_value,
            "response_type": self.response_type.value,
            "message": self.message,
            "animation": self.animation,
            "timestamp": self.timestamp,
        }


# ── Thank-you templates ─────────────────────────────────────────

GIFT_THANKS: dict[GiftLevel, list[str]] = {
    GiftLevel.NORMAL: [
        "感谢{user}送来的{gift}！",
        "谢谢{user}的{gift}支持！",
        "{user}送的{gift}收到啦，谢谢！",
    ],
    GiftLevel.PREMIUM: [
        "哇！感谢{user}送来的{gift}！老板大气！",
        "谢谢{user}的{gift}！太给力了！",
        "{user}老板的{gift}！土豪求抱大腿~",
    ],
    GiftLevel.SUPER: [
        "天哪！{user}送了一个{gift}！全场起立！谢谢老板！",
        "🎉 {user}的{gift}！家人们看到了吗！这也太豪了！谢谢支持！",
        "哇！{user}老板送的{gift}！老张快看！这是咱们直播间的大金主啊！",
    ],
}

# Animation mapping by gift level
GIFT_ANIMATIONS: dict[GiftLevel, str] = {
    GiftLevel.NORMAL: "smile",
    GiftLevel.PREMIUM: "thumbs_up",
    GiftLevel.SUPER: "wave",
}


class GiftAgent:
    """Monitor gifts and generate thank-you interactions.

    Usage::

        agent = GiftAgent()
        interaction = agent.on_gift("王总", "嘉年华", 3000.0, GiftLevel.SUPER)
        await host_say(interaction.message)
    """

    def __init__(self, cooldown_seconds: float = 2.0) -> None:
        self.cooldown_seconds = cooldown_seconds
        self._last_response_time: float = 0.0
        self._user_gift_total: dict[str, float] = {}       # username -> total value
        self._user_gift_count: dict[str, int] = {}         # username -> gift count
        self._total_gift_value: float = 0.0
        self._total_gift_count: int = 0
        self._interaction_history: list[GiftInteraction] = []
        self._super_gift_threshold: float = 100.0

    def on_gift(
        self, username: str, gift_name: str, gift_value: float,
        gift_level: GiftLevel, platform: str = "unknown",
    ) -> GiftInteraction | None:
        """Process a gift event, return interaction if applicable."""

        if not username:
            return None

        # Cooldown (skip for super gifts)
        now = time.time()
        if gift_level != GiftLevel.SUPER:
            if now - self._last_response_time < self.cooldown_seconds:
                return None

        # Track
        self._user_gift_total[username] = self._user_gift_total.get(username, 0) + gift_value
        self._user_gift_count[username] = self._user_gift_count.get(username, 0) + 1
        self._total_gift_value += gift_value
        self._total_gift_count += 1

        total_value = self._user_gift_total[username]

        # Determine response type
        if gift_level == GiftLevel.SUPER:
            response_type = GiftResponseType.SPECIAL
        elif total_value >= self._super_gift_threshold:
            response_type = GiftResponseType.TOP_DONOR
        elif gift_level == GiftLevel.PREMIUM:
            response_type = GiftResponseType.ANIMATION
        else:
            response_type = GiftResponseType.THANKS

        # Generate message
        templates = GIFT_THANKS.get(gift_level, GIFT_THANKS[GiftLevel.NORMAL])
        message = random.choice(templates).format(user=username, gift=gift_name)

        # Add cumulative info for top donors
        if response_type == GiftResponseType.TOP_DONOR:
            message += f" 累计已送出{total_value:.0f}元的礼物支持！"

        # Animation
        animation = GIFT_ANIMATIONS.get(gift_level, "idle")

        interaction = GiftInteraction(
            username=username,
            platform=platform,
            gift_name=gift_name,
            gift_value=gift_value,
            gift_level=gift_level,
            total_value=total_value,
            response_type=response_type,
            message=message,
            animation=animation,
            timestamp=now,
        )

        self._last_response_time = now
        self._interaction_history.append(interaction)
        if len(self._interaction_history) > 500:
            self._interaction_history = self._interaction_history[-200:]

        logger.info("Gift: %s sent %s (value=%.1f, level=%s, total=%.1f)",
                     username, gift_name, gift_value, gift_level.value, total_value)

        return interaction

    def get_top_donors(self, top_n: int = 10) -> list[dict]:
        """Get top donors by total gift value."""
        sorted_donors = sorted(
            self._user_gift_total.items(), key=lambda x: x[1], reverse=True
        )[:top_n]
        return [
            {"username": u, "total_value": v, "gift_count": self._user_gift_count.get(u, 0)}
            for u, v in sorted_donors
        ]

    def get_stats(self) -> dict:
        return {
            "total_gift_value": self._total_gift_value,
            "total_gift_count": self._total_gift_count,
            "unique_donors": len(self._user_gift_total),
            "top_donors": self.get_top_donors(5),
            "recent_interactions": [
                i.to_dict() for i in self._interaction_history[-10:]
            ],
        }
