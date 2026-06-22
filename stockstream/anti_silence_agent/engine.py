"""Anti-silence agent — prevent dead air in the live room.

If 30 seconds pass without viewer interaction:
- Auto-generate a simulated viewer question
- Male and female hosts continue the discussion
- Keep the room alive and engaging

Features:
- Silence detection (configurable threshold)
- Auto-question generation with stock context
- Conversation flow maintenance
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SilenceAction:
    """An anti-silence intervention."""
    action_type: str         # "question" | "topic_switch" | "market_joke" | "recap"
    message: str             # The generated audience question or host line
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "action_type": self.action_type,
            "message": self.message,
            "timestamp": self.timestamp,
        }


# ── Question Templates ───────────────────────────────────────────

VIEWER_QUESTIONS: list[str] = [
    # Stock questions
    "老张，{stock}今天怎么看？",
    "人工智能，{stock}还能持有吗？",
    "老张老张，{stock}现在是买点吗？",
    "主播看看{stock}，我的成本价比较高，要不要割肉？",
    "小财妹，{stock}今天跌了不少，是机会还是风险？",
    "我想问一下{stock}，今天放量下跌意味着什么？",
    "请问{stock}现在进去合适吗？刚跌了{change}%",
    "老张帮我看下{stock}，我拿了半个月了，还能继续拿吗？",
    "主播看看{stock}和{stock2}哪个更有投资价值？",
    "{stock}今天这个走势，是不是有主力在里面搞事情？",
    # Market questions
    "老张，今天大盘怎么看？是调整还是变盘？",
    "人工智能，今天市场整体比较弱，是什么原因？",
    "下午还有机会吗？上午跌了这么多。",
    "北向资金今天是流入还是流出？",
    "现在这个位置适合加仓吗？",
    "感觉最近市场没有方向，老张怎么看？",
    # Technical questions
    "请问MACD指标要怎么用？",
    "老张能讲讲怎么看主力资金流向吗？",
    "均线系统怎么设置比较好？",
    "成交量突然放大是什么信号？",
]

# ── Topic switch prompts ────────────────────────────────────────

TOPIC_SWITCHES: list[str] = [
    "好，聊完这个话题，我们来看一个有意思的板块。",
    "说到这，老张你关注到最近的热点新闻了吗？",
    "换个话题，最近有一个特别火的板块，大家知道是什么吗？",
    "暂时没有人提问，那我来给大家分享一个今天的财经冷知识。",
    "这会儿没人互动，那咱们来盘点一下今天的财经热点。",
]

# ── Market jokes ────────────────────────────────────────────────

MARKET_JOKES: list[str] = [
    "趁这会儿没人，我给大家讲个段子。有人说炒股的艺术就是：高点买，低点卖，剩下的交给命运。",
    "老张你知道吗，有个段子说：新股民看K线，老股民看基本面，高手看心情。",
    "巴菲特说别人恐惧我贪婪，于是我在A股贪婪了三年，现在终于恐惧了。",
    "今天的冷场让我想起一个笑话：股市就像电梯，上去很慢，下来很快，而且你永远不知道会停在哪一层。",
]


class AntiSilenceAgent:
    """Prevent dead air by auto-generating viewer interactions.

    Usage::

        agent = AntiSilenceAgent(silence_threshold=30)
        # When detecting silence:
        action = agent.get_action(watch_list=["600519", "000001"])
        await host_respond(action.message)
    """

    def __init__(
        self,
        silence_threshold: float = 30.0,
        question_probability: float = 0.6,
    ) -> None:
        self.silence_threshold = silence_threshold
        self.question_probability = question_probability
        self._last_interaction_time: float = 0.0  # Start as "long silence" for testing
        self._silence_count = 0
        self._action_history: list[SilenceAction] = []
        self._used_questions: list[int] = []

    def record_interaction(self) -> None:
        """Record that an interaction occurred, resetting the silence timer."""
        self._last_interaction_time = time.time()

    def is_silent(self) -> bool:
        """Check if the room is currently silent."""
        return time.time() - self._last_interaction_time > self.silence_threshold

    def get_silence_duration(self) -> float:
        """Get current silence duration in seconds."""
        return time.time() - self._last_interaction_time

    def get_action(
        self, watch_list: list[str] | None = None,
    ) -> SilenceAction | None:
        """Get an anti-silence action if the room is silent."""
        if not self.is_silent():
            return None

        self._silence_count += 1
        watch_list = watch_list or ["600519", "000001"]

        # Mix action types based on silence severity
        r = random.random()
        if r < self.question_probability:
            action_type = "question"
            message = self._generate_question(watch_list)
        elif r < 0.85:
            action_type = "topic_switch"
            message = random.choice(TOPIC_SWITCHES)
        else:
            action_type = "market_joke"
            message = random.choice(MARKET_JOKES)

        action = SilenceAction(
            action_type=action_type,
            message=message,
        )
        self._action_history.append(action)
        # 24h: 裁剪旧记录
        if len(self._action_history) > self._action_history_max:
            self._action_history = self._action_history[-100:]
        self._last_interaction_time = time.time()

        logger.info("AntiSilence: triggered %s (silence_count=%d)", action_type, self._silence_count)
        return action

    def _generate_question(self, watch_list: list[str]) -> str:
        """Generate a stock-specific question."""
        stock = random.choice(watch_list)
        stock2 = random.choice(watch_list)
        if stock2 == stock:
            stock2 = random.choice(watch_list) if len(watch_list) > 1 else "000858"

        template = self._pick_question()
        change = random.choice(["1.5", "2.3", "3.1", "0.8", "4.2"])
        return template.format(stock=stock, stock2=stock2, change=change)

    def _pick_question(self) -> str:
        available = [i for i in range(len(VIEWER_QUESTIONS)) if i not in self._used_questions[-5:]]
        if not available:
            available = list(range(len(VIEWER_QUESTIONS)))

        idx = random.choice(available)
        self._used_questions.append(idx)
        if len(self._used_questions) > 100:
            self._used_questions = self._used_questions[-30:]
        return VIEWER_QUESTIONS[idx]

    def get_stats(self) -> dict:
        return {
            "silence_count": self._silence_count,
            "silence_threshold": self.silence_threshold,
            "current_silence_duration": self.get_silence_duration(),
            "is_silent": self.is_silent(),
        }
