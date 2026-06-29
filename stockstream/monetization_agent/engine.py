"""Monetization agent — commercial operations.

Supports:
- Membership guidance
- Course promotion
- Community引流 (community traffic)
- Advertisement insertion

Rules:
- Trigger every 30 minutes
- Natural and conversational tone
- No aggressive marketing
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class MonetizeType(str, Enum):
    MEMBERSHIP = "membership"         # 会员引导
    COURSE = "course"                 # 课程推广
    COMMUNITY = "community"           # 社群引流
    AD = "advertisement"              # 广告插播


@dataclass()
class MonetizeAction:
    """A commercial operation action."""
    action_type: MonetizeType
    message: str
    priority: int = 5          # lower = less intrusive
    cooldown_minutes: int = 30
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "action_type": self.action_type.value,
            "message": self.message,
            "priority": self.priority,
            "timestamp": self.timestamp,
        }


# ── Templates ────────────────────────────────────────────────────

MEMBERSHIP_TEMPLATES: list[str] = [
    "很多朋友问怎么学到更多干货，告诉大家一个好消息，开通会员可以解锁深度分析和实时策略哦~详情看右下角。",
    "想要获取每日股票池和操作策略的朋友，可以看看我们的会员服务，性价比超高！",
    "老张每天都会在会员群里分享独家分析报告，有兴趣的朋友了解一下~",
    "直播间左上角有会员入口，加入会员享受专属分析服务！",
]

COURSE_TEMPLATES: list[str] = [
    "最近很多新朋友问怎么学炒股。说实话，我们这个《零基础学炒股》课程很适合新手，从入门到实战，学到就是赚到。",
    "不会选股、不会看盘、总是追涨杀跌？我们的系统课程帮你解决这些问题！想了解的朋友扣个1~",
    "很多人问怎么样才能在股市里稳定盈利。我们有一套完整的交易体系课程，学了之后保证你有思路！",
    "想学技术分析、学会看盘、学会选股的朋友，我们有专门的实战课程，可以了解一下。",
]

COMMUNITY_TEMPLATES: list[str] = [
    "想要和更多股友交流？加入我们的交流群，和老张以及其他炒股高手一起讨论！",
    "一个人炒股太孤单？加入我们的炒股社群，每天都有最新的内部分析分享~",
    "想进群的伙伴扣个666，我们有免费的炒股交流群，每天分享最新策略！",
    "很多朋友都在问交流群，感兴趣的朋友看下直播间公告，有加入方式~",
]

AD_TEMPLATES: list[str] = [
    "插播一个小消息，我们的合作券商现在有开户优惠活动，佣金万1.5起，有需要的朋友可以了解一下。",
    "今天有个好消息告诉家人们，某知名财经平台和我们合作了，给大家带来了专属福利~",
]


class MonetizationAgent:
    """Commercial operation agent for natural monetization.

    Usage::

        agent = MonetizationAgent(interval_minutes=30)
        action = agent.should_trigger()
        if action:
            await host_say(action.message)
    """

    def __init__(self, interval_minutes: int = 30) -> None:
        self.interval_seconds = interval_minutes * 60
        self._last_action_time: float = time.time()  # Don't trigger immediately
        self._action_history: list[MonetizeAction] = []
        self._action_history_max: int = 200  # 24h: 防止无界增长
        self._total_actions = 0
        # Rotate through types
        self._type_index = 0
        self._type_order: list[MonetizeType] = [
            MonetizeType.COMMUNITY,
            MonetizeType.MEMBERSHIP,
            MonetizeType.COURSE,
            MonetizeType.COMMUNITY,
        ]
        self._used_templates: dict[MonetizeType, list[int]] = {
            t: [] for t in MonetizeType
        }

    def should_trigger(self) -> MonetizeAction | None:
        """Check if it's time for a monetization action."""
        now = time.time()
        if now - self._last_action_time < self.interval_seconds:
            return None

        # Pick type (rotate)
        mtype = self._type_order[self._type_index % len(self._type_order)]
        self._type_index += 1

        # Pick template
        templates = self._get_templates(mtype)
        template = self._pick_template(mtype, templates)

        action = MonetizeAction(
            action_type=mtype,
            message=template,
            cooldown_minutes=int(self.interval_seconds / 60),
            timestamp=now,
        )

        self._last_action_time = now
        self._total_actions += 1
        self._action_history.append(action)
        # 24h: 裁剪旧记录，每30分钟触发一次，200条可容纳100小时
        if len(self._action_history) > self._action_history_max:
            self._action_history = self._action_history[-100:]

        logger.info("Monetization: %s triggered (total=%d)", mtype.value, self._total_actions)
        return action

    def _get_templates(self, mtype: MonetizeType) -> list[str]:
        if mtype == MonetizeType.MEMBERSHIP:
            return MEMBERSHIP_TEMPLATES
        elif mtype == MonetizeType.COURSE:
            return COURSE_TEMPLATES
        elif mtype == MonetizeType.COMMUNITY:
            return COMMUNITY_TEMPLATES
        else:
            return AD_TEMPLATES

    def _pick_template(self, mtype: MonetizeType, templates: list[str]) -> str:
        used = self._used_templates[mtype]
        available = [i for i in range(len(templates)) if i not in used[-3:]]
        if not available:
            available = list(range(len(templates)))

        idx = random.choice(available)
        used.append(idx)
        if len(used) > 50:
            self._used_templates[mtype] = used[-20:]
        return templates[idx]

    def force_trigger(self, mtype: MonetizeType | None = None) -> MonetizeAction:
        """Force a monetization action."""
        if mtype is None:
            mtype = random.choice(list(MonetizeType))
        templates = self._get_templates(mtype)
        message = random.choice(templates)
        action = MonetizeAction(
            action_type=mtype,
            message=message,
        )
        self._action_history.append(action)
        self._total_actions += 1
        return action

    def get_stats(self) -> dict:
        return {
            "total_actions": self._total_actions,
            "interval_minutes": self.interval_seconds / 60,
            "recent_actions": [
                a.to_dict() for a in self._action_history[-5:]
            ],
        }
