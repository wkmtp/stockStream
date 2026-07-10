"""Operation agent — AI-driven live room operations.

Monitors engagement metrics and auto-adjusts content to optimize:
- Retention rate (停留率)
- Interaction rate (互动率)
- Follow rate (关注率)
- Conversion rate (转化率)

If interaction drops, auto-switch topics:
- Hot sectors
- Trending stocks
- Finance fun facts
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class OperationAction(str, Enum):
    """Types of operation interventions."""
    TOPIC_SWITCH = "topic_switch"         # Switch discussion topic
    HOT_STOCK_ALERT = "hot_stock_alert"   # Highlight trending stock
    ENGAGEMENT_BOOST = "engagement_boost" # Boost interaction
    SENTIMENT_CHECK = "sentiment_check"   # Check viewer sentiment
    SPEED_UP = "speed_up"                # Accelerate pace
    SLOW_DOWN = "slow_down"              # Decelerate pace


@dataclass()
class OperationAdvice:
    """Operation agent's advice for content adjustment."""
    action: OperationAction
    topic: str = ""
    stock_code: str = ""
    reason: str = ""
    urgency: int = 5          # 1-10, higher = more urgent
    timestamp: float = field(default_factory=time.time)
    message: str = ""         # What to say to hosts

    def to_dict(self) -> dict:
        return {
            "action": self.action.value,
            "topic": self.topic,
            "stock_code": self.stock_code,
            "reason": self.reason,
            "urgency": self.urgency,
            "message": self.message,
        }


class OperationAgent:
    """AI operations director for live room optimization.

    Monitors:
    - danmu volume (弹幕量)
    - online viewers (在线人数)
    - like volume (点赞量)
    - gift volume (礼物量)

    Triggers interventions when engagement drops.
    """

    def __init__(
        self,
        danmu_threshold: int = 5,          # danmu per minute threshold
        viewer_threshold: int = 10,        # min viewers
        cooldown_seconds: float = 60.0,
    ) -> None:
        self.danmu_threshold = danmu_threshold
        self.viewer_threshold = viewer_threshold
        self.cooldown_seconds = cooldown_seconds
        self._last_action_time: float = 0.0
        self._advice_history: list[OperationAdvice] = []
        self._total_advices = 0
        # Time-series tracking
        self._danmu_history: list[tuple[float, int]] = []
        self._viewer_history: list[tuple[float, int]] = []
        self._intervention_topics: list[str] = [
            "机器人概念", "新能源", "人工智能", "半导体", "白酒",
            "数字经济", "消费电子", "光伏", "医药", "军工",
        ]
        self._used_topics: list[int] = []

    def evaluate(
        self, danmu_per_minute: float, viewer_count: int,
        like_per_minute: float, gift_per_minute: float,
    ) -> OperationAdvice | None:
        """Evaluate engagement metrics and return advice if needed."""

        now = time.time()
        if now - self._last_action_time < self.cooldown_seconds:
            return None

        # Track history
        self._danmu_history.append((now, int(danmu_per_minute)))
        self._viewer_history.append((now, viewer_count))
        # Keep bounded
        if len(self._danmu_history) > 300:
            self._danmu_history = self._danmu_history[-100:]
        if len(self._viewer_history) > 300:
            self._viewer_history = self._viewer_history[-100:]

        # Check conditions
        advice = None

        # 1. Danmu too low → switch topic
        if danmu_per_minute < self.danmu_threshold and viewer_count > self.viewer_threshold:
            topic = self._pick_topic()
            advice = OperationAdvice(
                action=OperationAction.TOPIC_SWITCH,
                topic=topic,
                reason=f"弹幕互动过低 ({danmu_per_minute}/min)，建议切换话题",
                urgency=7,
                message=f"观众们好像对现在的话题不太感兴趣，老张我们聊一下{topic}板块吧？",
            )

        # 2. Viewer count dropping
        elif self._is_dropping("viewer"):
            advice = OperationAdvice(
                action=OperationAction.ENGAGEMENT_BOOST,
                reason="在线人数持续下降",
                urgency=8,
                message="直播间人数在下降，我们加快节奏，来点干货！",
            )

        # 3. Low like rate
        elif like_per_minute < 1 and viewer_count > 50:
            advice = OperationAdvice(
                action=OperationAction.ENGAGEMENT_BOOST,
                reason="点赞率极低",
                urgency=5,
                message="各位老铁，如果觉得我们的分析有帮助，动动小手点个赞支持一下~",
            )

        if advice:
            self._last_action_time = now
            self._advice_history.append(advice)
            self._total_advices += 1
            logger.info("OperationAgent: %s (urgency=%d)", advice.reason, advice.urgency)

        return advice

    def _is_dropping(self, metric: str) -> bool:
        """Check if a metric is trending down."""
        history = self._viewer_history if metric == "viewer" else self._danmu_history
        if len(history) < 6:
            return False

        # Compare last 3 vs previous 3 samples
        recent = [v for _, v in history[-3:]]
        previous = [v for _, v in history[-6:-3]]
        if not previous:
            return False

        avg_recent = sum(recent) / len(recent)
        avg_previous = sum(previous) / len(previous)

        if avg_previous == 0:
            return False

        # If dropped by more than 20%
        return (avg_previous - avg_recent) / avg_previous > 0.2

    def _pick_topic(self) -> str:
        available = [i for i in range(len(self._intervention_topics)) if i not in self._used_topics[-5:]]
        if not available:
            available = list(range(len(self._intervention_topics)))

        idx = random.choice(available)
        self._used_topics.append(idx)
        if len(self._used_topics) > 50:
            self._used_topics = self._used_topics[-20:]
        return self._intervention_topics[idx]

    def get_stats(self) -> dict:
        return {
            "total_advices": self._total_advices,
            "recent_advices": [
                a.to_dict() for a in self._advice_history[-5:]
            ],
        }
