"""Finance humor engine — generates financial puns and jokes for comic relief.

Designed to lighten the mood during a finance live stream, making the show
feel more like a talk show than a lecture.
"""

from __future__ import annotations

import random
import logging

from stockstream.dual_host.models import DialogTurn, Emotion, Speaker

logger = logging.getLogger(__name__)


# ── Humor segments (female setup → male punchline) ─────────────

_MARKET_JOKES: list[list[tuple[Speaker, str]]] = [
    [
        (Speaker.FEMALE, "今天市场怎么又绿了？"),
        (Speaker.MALE, "说明韭菜长势良好，春天到了嘛。"),
    ],
    [
        (Speaker.FEMALE, "为什么我一买就跌，一卖就涨？"),
        (Speaker.MALE, "因为主力发现你来了，监控到你的账户了。"),
        (Speaker.FEMALE, "那我换个账户行不行？"),
        (Speaker.MALE, "没用的，大数据时代，主力AI比你聪明多了。"),
    ],
    [
        (Speaker.FEMALE, "你觉得现在应该满仓、半仓还是空仓？"),
        (Speaker.MALE, "我觉得应该冷静仓，先管住手。"),
        (Speaker.FEMALE, "冷静仓是什么仓位？"),
        (Speaker.MALE, "就是啥也别买，先把心情控制住。"),
    ],
    [
        (Speaker.FEMALE, "最近有什么好股票推荐吗？"),
        (Speaker.MALE, "好股票很多，但适合你买的很少。"),
        (Speaker.FEMALE, "什么意思？"),
        (Speaker.MALE, "好股票不等于稳赚，考验的是心态和纪律，不是代码。"),
    ],
    [
        (Speaker.FEMALE, "牛市什么时候来啊？"),
        (Speaker.MALE, "等你不问这个问题的时候，就来了。"),
        (Speaker.FEMALE, "那我天天问行不行？"),
        (Speaker.MALE, "那你就是牛市最大的阻力。"),
    ],
    [
        (Speaker.FEMALE, "有人说炒股是投资，有人说炒股是赌博，你觉得呢？"),
        (Speaker.MALE, "看你怎么操作了。研究基本面的是投资，研究技术面的是投机，看别人买啥你买啥的是消费。"),
    ],
    [
        (Speaker.FEMALE, "我朋友说他今年的目标是翻倍，你觉得靠谱吗？"),
        (Speaker.MALE, "先定一个小目标——不亏钱。翻倍的事，看看新闻就够了。"),
    ],
    [
        (Speaker.FEMALE, "怎么看那些教人炒股的网红大V？"),
        (Speaker.MALE, "记住一句话——真正赚到钱的人，没空教别人赚钱。"),
    ],
    [
        (Speaker.FEMALE, "散户为什么总是亏钱？"),
        (Speaker.MALE, "因为散户有三个特点：底部不敢买，顶部不舍得卖，中间频繁操作。"),
        (Speaker.FEMALE, "好像说的就是我..."),
        (Speaker.MALE, "没事，你不是一个人，全国一亿多散户陪着你。"),
    ],
    [
        (Speaker.FEMALE, "什么叫价值投资？"),
        (Speaker.MALE, "就是买了一个股票之后一直跌，你安慰自己说在价值投资。"),
        (Speaker.FEMALE, "那技术分析呢？"),
        (Speaker.MALE, "买了一个股票一直跌，你画各种线证明它应该涨。"),
    ],
]

# ── Quick one-liners ───────────────────────────────────────────

_ONE_LINERS: list[str] = [
    "今天又是学好经济学的一天——主要是学到了什么叫'别人恐惧我恐惧，别人贪婪我更恐惧'。",
    "有人说股市是经济的晴雨表，我想说那这块表可能进水了。",
    "今天市场给我的感觉就是——涨了怕踏空，跌了怕套牢，不涨不跌又嫌没行情。",
    "散户最大的特点：仓位决定观点，买了就拼命找利好，卖了就疯狂搜利空。",
    "股市定律：你看好的股票永远不会跌到你心里那个价位，等你不想买了它就暴涨了。",
    "我刚入市的时候觉得K线图很复杂，现在觉得更复杂的是市场里的人心。",
    "亏钱的经历告诉我们一个道理——下次不会亏得更多。",
    "市场总是在绝望中见底，在犹豫中盘整，在狂热中见顶，在后悔中轮回。",
    "最好的投资策略可能是：把你自己的交易记录反过来做。",
    "股票最大的魅力就是——无论今天多惨，你都会期待明天。",
]


class FinanceHumorEngine:
    """Deliver a dose of financial humor to keep the show lively."""

    def generate_dialogue(self) -> list[DialogTurn]:
        """Generate a 2-4 turn humorous dialogue.

        Returns:
            List of DialogTurn forming a short comedy sketch.
        """
        sketch = random.choice(_MARKET_JOKES)
        turns: list[DialogTurn] = []
        for speaker, text in sketch:
            turns.append(DialogTurn(
                speaker=speaker,
                text=text,
                emotion=Emotion.HUMOROUS,
                is_question=(speaker == Speaker.FEMALE and ("？" in text or "?" in text)),
            ))
        return turns

    def one_liner(self) -> str:
        """Return a single financial joke line."""
        return random.choice(_ONE_LINERS)

    def opener_joke(self) -> DialogTurn:
        """A joke suitable for show opening or transitions."""
        return DialogTurn(
            speaker=Speaker.MALE,
            text=random.choice(_ONE_LINERS),
            emotion=Emotion.HUMOROUS,
        )
