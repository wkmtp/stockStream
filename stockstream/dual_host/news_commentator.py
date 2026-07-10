"""News commentator — fetch and discuss financial news in dual-host style.

Every 15 minutes, fetches recent financial headlines and generates a
30-second light discussion between the two hosts.
"""

from __future__ import annotations

import logging
import random
import uuid
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


# ── Fallback news templates (when live news fetch fails) ───────

_FALLBACK_NEWS: list[list[tuple[str, str]]] = [
    # (headline, discussion_point)
    [
        ("北向资金今日动向", "北向资金被很多人称为聪明资金，它们的进出往往反映了外资对A股的短期态度"),
    ],
    [
        ("沪深两市成交额变化", "成交额是市场的温度计，量能大小直接决定了行情的持续性"),
    ],
    [
        ("近期热门板块轮动规律", "板块轮动是A股的常态，但要搞清楚轮动的底层逻辑——是资金驱动还是业绩驱动"),
    ],
    [
        ("央行政策最新动向", "货币政策的变化对股市有直接影响，流动性宽松的时候股市往往表现更好"),
    ],
    [
        ("上市公司季报解读", "财报季是检验公司成色的时候，能交出好成绩的公司才值得长期关注"),
    ],
    [
        ("全球市场联动效应", "A股虽然有自己的节奏，但美股期货和港股走势还是会通过情绪面影响我们"),
    ],
    [
        ("基金持仓变动分析", "从公募基金的持仓变化可以窥见机构投资者的态度，他们重仓的行业往往有持续性"),
    ],
    [
        ("政策利好行业梳理", "政策是A股最重要的催化剂之一，但记住——想清楚政策离业绩有多远"),
    ],
]


class NewsCommentator:
    """Fetch and discuss financial news in the talk show format."""

    def __init__(self, emotion_engine: EmotionEngine | None = None) -> None:
        self.emotion = emotion_engine or EmotionEngine()
        self._used_news: set[str] = set()

    async def get_commentary(self) -> DialogueScript:
        """Generate a 30-second news commentary dialogue.

        Returns:
            DialogueScript with ~4-6 turns.
        """
        # Try live news fetch
        news = await self._fetch_live_news()

        turns = self._build_dialogue(news)
        self._used_news.add(news[0][0])

        return DialogueScript(
            segment_id=uuid.uuid4().hex[:8],
            segment_type=ShowSegmentType.NEWS_COMMENTARY,
            topic=news[0][0],
            turns=turns,
        )

    async def _fetch_live_news(self) -> list[tuple[str, str]]:
        """Attempt to fetch real financial news; fall back to templates."""
        # Try AkShare news API
        try:
            import asyncio
            def _fetch():
                import akshare as ak
                try:
                    df = ak.stock_news_em()
                    if df is not None and not df.empty:
                        headlines = df.head(10)
                        return [(row.get("title", "") or row.get("content", "")[:50],
                                 row.get("content", "")[:100] or "")
                                for _, row in headlines.iterrows()
                                if row.get("title") or row.get("content")]
                except Exception:
                    pass
                return None
            result = await asyncio.to_thread(_fetch)
            if result:
                # Pick one not recently used
                available = [r for r in result if r[0] not in self._used_news]
                if available:
                    return [random.choice(available)]
        except Exception as exc:
            logger.debug("Live news fetch failed: %s", exc)

        # Fallback: pick a template not recently used
        available = [n for n in _FALLBACK_NEWS if n[0][0] not in self._used_news]
        if not available:
            self._used_news.clear()
            available = _FALLBACK_NEWS
        return random.choice(available)

    def _build_dialogue(self, news: list[tuple[str, str]]) -> list[DialogTurn]:
        """Build 4-6 turn dialogue from a news item."""
        headline, context = news[0]
        turns: list[DialogTurn] = []

        # Female: introduce the news
        intro_templates = [
            f"我们来看一条财经快讯——{headline}，你怎么看这事？",
            f"刚刚看到一条消息，{headline}，给咱们说说呗？",
            f"来了条新闻，{headline}，这个对市场有什么影响？",
        ]
        turns.append(DialogTurn(
            speaker=Speaker.FEMALE,
            text=random.choice(intro_templates),
            emotion=Emotion.THINKING,
            is_question=True,
        ))

        # Male: analysis
        analysis = context if context else (
            f"这条消息值得关注，{headline}对相关板块会有直接影响。"
            f"如果后续有更多政策或数据出来，我们要及时跟进分析。"
        )
        turns.append(DialogTurn(
            speaker=Speaker.MALE,
            text=analysis,
            emotion=self.emotion.detect(analysis, Speaker.MALE),
        ))

        # Female: practical follow-up
        followups = [
            "那对于我们普通投资者来说，需要做什么准备？",
            "这个消息会影响哪些板块？",
            "短期操作上有什么建议吗？",
        ]
        turns.append(DialogTurn(
            speaker=Speaker.FEMALE,
            text=random.choice(followups),
            emotion=Emotion.THINKING,
            is_question=True,
        ))

        # Male: actionable advice
        turns.append(DialogTurn(
            speaker=Speaker.MALE,
            text="短期先关注相关板块的反应，如果资金开始流入说明市场认可这个消息。"
                  "但如果高开低走就要警惕，说明是消息出货。记住了，消息永远只是催化剂，"
                  "最终还是要看资金面的确认。",
            emotion=Emotion.SERIOUS,
        ))

        # Female: wrap
        wraps = [
            "好的，我们继续关注后续发展。",
            "明白了，感谢老师的分析！我们继续下一个话题。",
            "学到了，消息面结合资金面综合判断，不能只看消息炒股！",
        ]
        turns.append(DialogTurn(
            speaker=Speaker.FEMALE,
            text=random.choice(wraps),
            emotion=Emotion.HAPPY,
        ))

        return turns
