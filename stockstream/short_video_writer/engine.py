"""Short video writer — generate copywriting for short video clips.

Generates for each clip:
- Title (标题)
- Cover text (封面文案)
- Tags (标签)
- Description (简介)

Style: 财经爆款风格 (viral finance style)
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class VideoCopy:
    """Copywriting package for a short video clip."""
    clip_id: str
    title: str
    cover_text: str
    tags: list[str]
    description: str
    hashtag: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "clip_id": self.clip_id,
            "title": self.title,
            "cover_text": self.cover_text,
            "tags": self.tags,
            "description": self.description,
            "hashtag": self.hashtag,
        }


# ── Title templates (viral finance style) ────────────────────────

STOCK_TITLES: list[str] = [
    "涨疯了！{stock}突发异动，老张这样说！",
    "千万散户都懵了！{stock}到底发生了什么？",
    "{stock}突然跳水，是机会还是陷阱？",
    "巴菲特看了都沉默！{stock}这波操作太狠了！",
    "刚刚！{stock}传来重大消息，散户必看！",
    "开盘10分钟！{stock}这样走，今天有大事发生！",
    "今天{stock}的秘密，99%的人不知道！",
    "别慌！{stock}调整就是机会，老张深度解读！",
]

GENERAL_TITLES: list[str] = [
    "今天A股太刺激了！老张的分析说到心坎里了！",
    "炒股十年不如看这次分析，散户必看！",
    "为什么你总是亏？看完这段视频你就懂了！",
    "散户必看！老张的三个炒股秘诀，今天免费分享！",
    "今天直播间太炸了！这段分析价值百万！",
    "A股机会来了！这三只股票值得关注！",
    "不到30秒，改变你的炒股思维！",
    "知道这个消息后，我再也不追涨杀跌了！",
]

COVER_TEXTS: list[str] = [
    "散户必看",
    "深度解读",
    "精彩瞬间",
    "价值百万",
    "不看后悔",
    "干货满满",
    "专业分析",
    "独家解读",
]

TAG_POOL: list[str] = [
    "财经", "A股", "股票", "炒股", "投资", "理财",
    "牛股", "涨停", "选股技巧", "股票分析", "财经知识",
    "散户必看", "股市分析", "炒股教程", "技术分析",
    "价值投资", "短线交易", "龙头股", "热门板块",
    "财经直播", "股票推荐",
]

DESCRIPTION_TEMPLATES: list[str] = [
    "【关注我们，每天精彩分析不错过】📈\n{title}\n\n#财经 #A股 #股票 #炒股技巧 #投资",
    "老张深度解读市场，看完你就知道怎么操作了！\n\n{title}\n\n点赞关注，每天都有干货！",
    "直播间高能片段，错过直播的朋友必看！\n\n{title}\n\n#炒股 #投资 #A股行情",
]


class ShortVideoWriter:
    """Generate viral-style finance copywriting for video clips.

    Usage::

        writer = ShortVideoWriter()
        copy = writer.generate(clip_id="abc123", stock_name="贵州茅台")
        print(copy.title, copy.tags)
    """

    def __init__(self, max_tags: int = 8) -> None:
        self.max_tags = max_tags
        self._copy_history: list[VideoCopy] = []
        self._total_generated = 0

    def generate(
        self, clip_id: str, trigger: str = "",
        stock_name: str = "", topic: str = "",
    ) -> VideoCopy:
        """Generate copywriting for a clip."""

        # Title
        if stock_name or topic:
            stock = stock_name or topic
            title = random.choice(STOCK_TITLES).format(stock=stock)
        else:
            title = random.choice(GENERAL_TITLES)

        # Cover text
        cover_text = random.choice(COVER_TEXTS)

        # Tags
        tags = random.sample(TAG_POOL, min(self.max_tags, len(TAG_POOL)))

        # Description
        desc_template = random.choice(DESCRIPTION_TEMPLATES)
        description = desc_template.format(title=title)

        # Hashtag
        hashtag = f"#财经直播 #{'#'.join(tags[:3])}"

        copy = VideoCopy(
            clip_id=clip_id,
            title=title,
            cover_text=cover_text,
            tags=tags,
            description=description,
            hashtag=hashtag,
        )
        self._copy_history.append(copy)
        self._total_generated += 1
        return copy

    def generate_for_trigger(
        self, clip_id: str, trigger: str, stock_name: str = "",
    ) -> VideoCopy:
        """Generate tailored copy based on the clip trigger type."""
        if trigger == "hot_stock":
            title = random.choice(STOCK_TITLES).format(stock=stock_name or "某股")
            cover_text = "🔥 突发异动"
        elif trigger == "gift_peak":
            title = f"老板大气！{stock_name or '直播间'}送出超级大礼！全场沸腾！"
            cover_text = "🎁 礼物狂潮"
        elif trigger == "high_interaction":
            title = "直播间炸了！这段对话让千万粉丝都炸锅了！"
            cover_text = "💥 高能时刻"
        elif trigger == "memorable":
            title = f"老张这番话说到心里了！{stock_name or '炒股'}必看！"
            cover_text = "⭐ 精彩点评"
        else:
            title = random.choice(GENERAL_TITLES)
            cover_text = random.choice(COVER_TEXTS)

        tags = random.sample(TAG_POOL, min(self.max_tags, len(TAG_POOL)))
        description = f"{title}\n\n点赞关注，每天都有精彩内容！#财经 #A股 #炒股"
        hashtag = f"#财经直播 #{'#'.join(tags[:3])}"

        copy = VideoCopy(
            clip_id=clip_id,
            title=title,
            cover_text=cover_text,
            tags=tags,
            description=description,
            hashtag=hashtag,
        )
        self._copy_history.append(copy)
        self._total_generated += 1
        return copy

    def get_stats(self) -> dict:
        return {
            "total_generated": self._total_generated,
        }
