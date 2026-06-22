"""Audience agent — simulates real viewer questions for interactive segments.

Maintains a pool of realistic viewer names and generates natural-sounding
questions about stocks, the market, and trading strategies.
"""

from __future__ import annotations

import random
import logging
from typing import Any

from stockstream.dual_host.emotion_engine import EmotionEngine
from stockstream.dual_host.models import (
    DialogTurn,
    DialogueScript,
    Emotion,
    ShowSegmentType,
    Speaker,
)

logger = logging.getLogger(__name__)

# ── Simulated audience members ─────────────────────────────────

_AUDIENCE_NAMES: list[str] = [
    "老王", "小李", "阿杰", "小芳", "小陈", "大刘",
    "阿明", "静静", "张老师", "老赵",
    "炒股新手小明", "持有茅台的老张", "刚入市的阿花",
    "全职韭菜小刚", "技术流阿豪", "价值投资的丽姐",
    "短线高手阿飞", "亏损30%的小白", "刚解套的老周",
]

# ── Question templates ─────────────────────────────────────────

_GENERAL_QUESTIONS: list[str] = [
    "老师，今天大盘怎么看？",
    "现在适合加仓吗？",
    "最近有没有什么好股票推荐？",
    "怎么看成交量比昨天小了？",
    "北向资金最近一直在流出，是不是说明外资不看好了？",
    "新手应该从哪些股票开始买？",
    "止损应该设在多少？5%还是10%？",
    "怎么判断一只股票是不是在底部？",
    "老师，仓位管理有没有什么简单的方法？",
    "追涨停板到底靠不靠谱？",
    "技术分析和基本面分析哪个更重要？",
    "怎么看龙虎榜的数据？",
    "什么叫右侧交易，什么叫左侧交易？",
    "中签的新股什么时候卖比较合适？",
    "ETF和个股哪个更适合新手？",
]

_STOCK_QUESTIONS: list[str] = [
    "{name}这个位置能不能买？",
    "老师看看{name}，现在要不要进场？",
    "{name}今天怎么了，要不要割？",
    "我持有{name}，成本{price}，现在该怎么办？",
    "{name}现在值得做长线吗？",
    "{name}从高位跌了{percent}%了，是不是可以抄底了？",
    "{name}的成交量突然放大了，怎么看？",
    "{name}已经连涨{count}天了，还能追吗？",
    "{name}昨天冲高回落，今天要不要卖？",
    "{name}的市盈率太高了，还有投资价值吗？",
]

_EMOTION_QUESTIONS: list[str] = [
    "大盘红的我慌，绿的我更慌，怎么办？",
    "我买什么跌什么，卖什么涨什么，是不是有神秘力量盯着我？",
    "一个月亏了20%，还有救吗？",
    "看着别人的股票天天涨，自己的股票天天横，心态崩了。",
    "去年赚的今年全亏回去了，该怎么调整？",
]


class AudienceAgent:
    """Simulate natural audience interaction with pre-generated questions.

    When real danmu are available, those take priority (via live_comment_fusion).
    This agent fills in when no real viewers are interacting.
    """

    def __init__(self, emotion_engine: EmotionEngine | None = None) -> None:
        self.emotion = emotion_engine or EmotionEngine()
        self._asked: set[str] = set()
        self._persona: dict[str, str] = dict(zip(_AUDIENCE_NAMES, _AUDIENCE_NAMES))

    def generate_question(self, watch_list: list[str] | None = None) -> dict:
        """Generate one simulated audience question.

        Args:
            watch_list: Current tracked stocks for contextual questions.

        Returns:
            Dict with 'username', 'question' keys.
        """
        # Pick a user persona not recently used
        name = random.choice(_AUDIENCE_NAMES)

        # Decide question type: 70% stock, 20% general, 10% emotion
        roll = random.random()
        if roll < 0.7 and watch_list:
            q_template = random.choice(_STOCK_QUESTIONS)
            stock = random.choice(watch_list)
            question = q_template.format(
                name=stock,
                price=str(random.randint(10, 500)),
                percent=str(random.randint(10, 50)),
                count=str(random.randint(3, 10)),
            )
        elif roll < 0.9:
            question = random.choice(_GENERAL_QUESTIONS)
        else:
            question = random.choice(_EMOTION_QUESTIONS)

        # Deduplicate
        key = f"{name}:{question}"
        if key in self._asked:
            return self.generate_question(watch_list)
        self._asked.add(key)

        # Limit memory
        if len(self._asked) > 200:
            self._asked = set(list(self._asked)[-100:])

        return {"username": name, "question": question}

    def generate_batch(self, count: int = 3,
                       watch_list: list[str] | None = None) -> list[dict]:
        """Generate multiple questions."""
        return [self.generate_question(watch_list) for _ in range(count)]

    def generate_qa_dialogue(
        self,
        question: dict,
        stock_contexts: dict[str, Any] | None = None,
    ) -> DialogueScript:
        """Generate a Q&A dialogue segment around one question.

        Args:
            question: Dict with 'username' and 'question'.
            stock_contexts: Known stock analysis contexts.

        Returns:
            DialogueScript with Female reading question → Male answering.
        """
        import uuid
        turns: list[DialogTurn] = []

        q_text = question["question"]
        username = question.get("username", "观众朋友")

        # Turn 1: Female reads the question
        turns.append(DialogTurn(
            speaker=Speaker.FEMALE,
            text=f"好，我们来看看{username}的问题——{q_text}",
            emotion=Emotion.HAPPY,
        ))

        # Turn 2: Male answers
        answer = self._generate_answer(q_text)
        turns.append(DialogTurn(
            speaker=Speaker.MALE,
            text=answer,
            emotion=self.emotion.detect(answer, Speaker.MALE),
        ))

        # Turn 3: Female response/clarification
        turns.append(DialogTurn(
            speaker=Speaker.FEMALE,
            text=self._female_qa_response(q_text, answer),
            emotion=Emotion.HAPPY,
        ))

        return DialogueScript(
            segment_id=uuid.uuid4().hex[:8],
            segment_type=ShowSegmentType.AUDIENCE_QA,
            topic=f"Q&A: {username}",
            turns=turns,
        )

    def _generate_answer(self, question: str) -> str:
        """Generate a reasonable-sounding answer."""
        if "买" in question or "进场" in question or "加仓" in question:
            return (
                "这个问题很好。我的建议是——先判断整体市场环境。"
                "如果大盘趋势向上，仓位不重的话可以轻仓尝试。"
                "但如果短期涨幅已经比较大，还是要等回调低吸。"
                "关键不是能不能买，而是买了之后怎么处理——"
                "设好止损位，错了就跑，不要犹豫。"
            )
        elif "卖" in question or "割" in question or "出" in question:
            return (
                "卖不卖取决于你当初为什么买。如果是短线交易，"
                "到了止损点该走就要走。如果是中长线投资，"
                "公司基本面没变的话，短期波动不用太慌。"
                "不过有一条铁律——如果一只股票占了你总仓位超过30%，"
                "不管涨跌都应该适当减持。"
            )
        elif "亏" in question or "跌" in question or "套" in question:
            return (
                "亏损是每个投资者的必修课，关键要从亏损中学到东西。"
                "我的建议是三件事：第一，复盘当初为什么买——逻辑还在不在。"
                "第二，控制后续的风险——绝对不要再加仓摊平成本了。"
                "第三，如果逻辑确实破了，果断止损。记住，本金安全永远第一。"
            )
        elif "新手" in question or "刚" in question or "小白" in question:
            return (
                "新手我的建议是三句话：第一，拿少量资金试水，不要把全部家当放进来。"
                "第二，先学基础知识再看盘，不要什么都没懂就开始买卖。"
                "第三，建立自己的交易纪律——什么时候买、什么时候卖，想清楚再动手。"
            )
        else:
            return (
                "感谢你的提问。由于问题比较宽泛，我说一个普适的原则——"
                "投资最重要的不是选股，而是仓位管理和风险控制。"
                "这两样做不好，选什么股票都没用。"
                "建议先把基础打牢，再谈赚钱的事。"
            )

    def _female_qa_response(self, _question: str, _answer: str) -> str:
        responses = [
            "好的，希望对这位朋友有帮助！我们继续看下一个问题。",
            "老师的建议很中肯，大家记住千万别追涨杀跌哦。",
            "感谢提问，也欢迎更多朋友来互动！",
            "学到了！仓位管理确实比临时做决策重要多了。",
        ]
        return random.choice(responses)
