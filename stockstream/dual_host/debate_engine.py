"""Debate engine — generate bull vs bear perspectives for live show engagement.

Creates balanced multi-angle discussions that present both sides of any
market situation, avoiding one-sided cheerleading.
"""

from __future__ import annotations

import random
import logging
from typing import Any

from stockstream.dual_host.emotion_engine import EmotionEngine
from stockstream.dual_host.models import DialogTurn, Emotion, Speaker

logger = logging.getLogger(__name__)


# ── Debate templates ───────────────────────────────────────────

# (male_bull, male_bear) pairs per scenario type

_STRONG_UP: list[tuple[str, str, str]] = [
    # (bull_point, bear_point, transition)
    (
        "从资金面看，主力今天大举流入，而且成交量配合得不错，短期还有惯性上冲的空间",
        "不过也要注意，连续上涨之后获利盘积累比较多，如果明天量能跟不上，可能会冲高回落",
        "所以追高还是要谨慎一些，这个位置不适合重仓杀入"
    ),
    (
        "技术形态很漂亮，均线多头排列，MACD也在零轴上方金叉，趋势没坏",
        "但是涨太快了往往调整也快，你看RSI已经在高位了，短期有回调需求",
        "我建议如果持有可以继续拿着，但这个时候新开仓风险收益比就不太好了"
    ),
    (
        "情绪面非常好，市场关注度高，而且有板块效应，资金在轮动",
        "不过高关注度也意味着容易被游资利用，追进去容易被割韭菜",
        "核心还是看基本面能不能支撑这个涨幅，如果是纯概念炒作就要小心"
    ),
]

_WEAK_DOWN: list[tuple[str, str, str]] = [
    (
        "跌到这个位置，估值已经比较合理了，而且成交量在萎缩，说明抛压在减轻",
        "问题是下跌趋势还没扭转，MACD还是死叉状态，现在进去有可能抄在半山腰",
        "稳妥的做法是等它缩量止跌企稳，出现放量阳线再考虑"
    ),
    (
        "如果公司基本面没有大问题，这种回调反而是逢低布局的机会",
        "可是主力资金还在持续流出，说明大资金不认同这个位置，短期可能还有新低",
        "追跌跟追涨一样危险，要有耐心等右侧信号"
    ),
    (
        "从长期看这个公司质地不错，现在的跌幅可能只是市场情绪在宣泄",
        "但是情绪这个东西很难量化，市场恐慌的时候什么估值都没用",
        "建议分批建仓，不要一把梭，控制好总仓位"
    ),
]

_NEUTRAL: list[tuple[str, str, str]] = [
    (
        "这个股票目前处于横盘整理阶段，多空双方在博弈，方向还没出来",
        "横盘久了要么向上突破要么向下跌破，现在进去就是在赌方向",
        "我的建议是等放量突破再跟进，目前先观望比较好"
    ),
    (
        "量能不大不小，涨跌幅也不大，这种状态说明市场在等待新的催化",
        "没有消息就是最大的利空，横盘消耗的是时间成本",
        "如果有其他更好的机会，不用把资金耗在这种不涨不跌的标的上"
    ),
]

_SECTOR_HOT: list[tuple[str, str, str]] = [
    (
        "这个板块今天集体爆发，龙头已经涨停，说明资金认可度很高，可能有持续性",
        "板块轮动太快了，今天最强明天可能就是最弱，追热点追不好就容易两头挨打",
        "关注龙头回调时的承接力度，如果龙头调整但是板块不跟跌，那才是真正强势"
    ),
    (
        "政策利好加资金共振，这种行情往往不会一天结束，可以关注后排补涨",
        "不过也要想清楚是真利好还是炒作，政策落地需要时间，短线炒作之后一地鸡毛的也不少",
        "核心还是看业绩能不能兑现，有基本面支撑的板块才有持续行情的底气"
    ),
]


class DebateEngine:
    """Generate balanced pro/con dialogues for a given stock or sector."""

    def __init__(self, emotion_engine: EmotionEngine | None = None) -> None:
        self.emotion = emotion_engine or EmotionEngine()

    def generate(self, context: dict[str, Any],
                 female_question: str | None = None) -> list[DialogTurn]:
        """Generate 3-4 turns of bull/bear debate.

        The pattern: Female asks → Male gives bull view → Male pivots to bear view → Female responds.

        Args:
            context: Market context dict from AnalysisService.
            female_question: Optional custom starting question.

        Returns:
            List of DialogTurn for the debate.
        """
        scenario = self._classify(context)
        turns: list[DialogTurn] = []

        # Pick a debate template
        if scenario == "strong_up":
            pool = _STRONG_UP
        elif scenario == "weak_down":
            pool = _WEAK_DOWN
        elif scenario == "sector_hot":
            pool = _SECTOR_HOT
        else:
            pool = _NEUTRAL

        bull, bear, transition = random.choice(pool)

        # Get stock name
        name = context.get("name", "这个股票")
        change_pct = context.get("change_pct", 0) or 0

        # Turn 1: Female question
        if female_question is None:
            if scenario == "strong_up":
                female_question = f"{name}今天涨了这么多，后面还能继续涨吗？"
            elif scenario == "weak_down":
                female_question = f"{name}最近跌得有点多啊，现在这个位置能不能抄底？"
            else:
                female_question = f"{name}今天走势平平，你怎么看？"

        turns.append(DialogTurn(
            speaker=Speaker.FEMALE,
            text=female_question,
            emotion=Emotion.THINKING,
            is_question=True,
        ))

        # Turn 2: Male bull view
        turns.append(DialogTurn(
            speaker=Speaker.MALE,
            text=bull,
            emotion=self.emotion.detect(bull, Speaker.MALE, context),
        ))

        # Turn 3: Male bear pivot
        turns.append(DialogTurn(
            speaker=Speaker.MALE,
            text=bear,
            emotion=Emotion.SERIOUS,
        ))

        # Turn 4: Female conclusion
        conclusions = {
            "strong_up": f"所以结论就是——{name}虽然强势，但别追着买？",
            "weak_down": "所以说，现在还不是抄底的时候，得再等等？",
            "sector_hot": "意思就是热点的确是热点，但追热点也得控制风险对吧？",
            "neutral": "那就先观望，等信号明确了再动手？",
        }
        turns.append(DialogTurn(
            speaker=Speaker.FEMALE,
            text=conclusions.get(scenario, conclusions["neutral"]),
            emotion=Emotion.THINKING,
            is_question=True,
        ))

        # Turn 5: Male wraps up
        turns.append(DialogTurn(
            speaker=Speaker.MALE,
            text=transition,
            emotion=Emotion.NEUTRAL,
        ))

        return turns

    def _classify(self, context: dict[str, Any]) -> str:
        """Classify the market scenario for debate template selection."""
        change_pct = context.get("change_pct", 0) or 0
        try:
            change_pct = float(change_pct)
        except (TypeError, ValueError):
            change_pct = 0

        if context.get("sector_name"):
            return "sector_hot"
        if change_pct > 5:
            return "strong_up"
        if change_pct < -3:
            return "weak_down"
        return "neutral"
