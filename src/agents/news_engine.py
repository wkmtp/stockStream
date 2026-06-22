"""财经新闻引擎 — 获取上市公司公告、财经新闻、政策消息，自动摘要生成主播脚本。

特性:
    1. 多源聚合: 上市公司公告 + 财经新闻 + 政策消息 + 板块消息
    2. 自动摘要: 长文提炼为口语化要点
    3. 脚本生成: 自动生成主播讨论脚本
    4. 去重过滤: 避免重复报道
    5. 时效性: 按时间排序，最新优先

用法:
    from src.agents.news_engine import NewsEngine

    ne = NewsEngine(bus=bus)
    await ne.start()
    news = await ne.fetch_latest()
    script = ne.generate_script(news)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


# ── Types ─────────────────────────────────────────────────────────────────


class NewsCategory(Enum):
    ANNOUNCEMENT = "announcement"   # 上市公司公告
    FINANCE_NEWS = "finance_news"   # 财经新闻
    POLICY = "policy"               # 政策消息
    SECTOR = "sector"               # 板块消息
    GLOBAL = "global"               # 国际市场


class NewsImpact(Enum):
    HIGH = "high"           # 重大影响
    MEDIUM = "medium"       # 中等影响
    LOW = "low"             # 一般
    NEUTRAL = "neutral"     # 中性


@dataclass
class NewsItem:
    """新闻条目。"""
    id: str = ""
    title: str = ""
    summary: str = ""
    content: str = ""
    category: NewsCategory = NewsCategory.FINANCE_NEWS
    impact: NewsImpact = NewsImpact.MEDIUM
    source: str = ""
    url: str = ""
    published_at: float = field(default_factory=time.time)
    related_symbols: list[str] = field(default_factory=list)
    related_sectors: list[str] = field(default_factory=list)
    key_points: list[str] = field(default_factory=list)  # 要点列表
    sentiment: str = "neutral"  # positive / negative / neutral

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "category": self.category.value,
            "impact": self.impact.value,
            "source": self.source,
            "related_symbols": self.related_symbols,
            "related_sectors": self.related_sectors,
            "key_points": self.key_points,
            "sentiment": self.sentiment,
        }


@dataclass
class NewsScript:
    """新闻口播脚本。"""
    title: str = ""
    script: str = ""
    duration_seconds: int = 30
    news_items: list[NewsItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "script": self.script,
            "duration_seconds": self.duration_seconds,
            "news_items": [n.to_dict() for n in self.news_items],
        }


class NewsEngine:
    """财经新闻引擎。

    推送事件:
      news.latest           — 最新新闻
      news.script           — 新闻口播脚本
      news.breaking         — 突发新闻
    """

    def __init__(self, bus: EventBus | None = None) -> None:
        self._bus: EventBus | None = bus
        self._running = False
        self._task: asyncio.Task | None = None
        self._news_cache: list[NewsItem] = []
        self._max_cache = 500
        self._seen_ids: set[str] = set()
        self._max_seen_ids = 10_000       # 24h 稳定性：去重集合上限
        self._seen_cleanup_interval = 600  # 每 10 分钟裁剪一次
        self._last_seen_cleanup = 0.0
        self._fetch_interval = 300  # 5分钟
        self._last_fetch = 0.0

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    # ── Lifecycle ───────────────────────────────────────────────────

    async def start(self) -> None:
        """启动新闻引擎。"""
        self._running = True
        self._task = asyncio.create_task(self._fetch_loop())

        bus = await self.bus

        @bus.on("director.action")
        async def _on_action(event):
            data = event.data or {}
            if data.get("action") == "news_brief":
                await self._push_news_script()

        logger.info("NewsEngine started")

    async def stop(self) -> None:
        """停止新闻引擎。"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("NewsEngine stopped")

    # ── Fetch Loop ──────────────────────────────────────────────────

    async def _fetch_loop(self) -> None:
        """定时抓取循环。"""
        while self._running:
            try:
                if time.time() - self._last_fetch > self._fetch_interval:
                    news = await self.fetch_latest()
                    if news:
                        bus = await self.bus
                        await bus.emit_async("news.latest", {
                            "count": len(news),
                            "news": [n.to_dict() for n in news[:5]],
                        })
                    self._last_fetch = time.time()

                await asyncio.sleep(60)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("NewsEngine fetch error: %s", exc)
                await asyncio.sleep(60)

    # ── News Fetching ───────────────────────────────────────────────

    async def fetch_latest(self, category: str = "", limit: int = 10) -> list[NewsItem]:
        """获取最新新闻。

        支持的数据源:
          - 上市公司公告 (后续接入东方财富/同花顺 API)
          - 财经新闻 (后续接入新闻聚合 API)
          - 政策消息
        """
        # 24h 稳定性：定期裁剪去重集合，只保留最近的 ID
        now = time.time()
        if len(self._seen_ids) >= self._max_seen_ids or (now - self._last_seen_cleanup) >= self._seen_cleanup_interval:
            # 保留最近 500 条缓存中的 ID
            keep_ids = {item.id for item in self._news_cache[-500:]}
            self._seen_ids &= keep_ids
            self._last_seen_cleanup = now
            logger.debug("NewsEngine: trimmed _seen_ids (was >= %d)", self._max_seen_ids)

        # 当前使用模拟数据，后续接入真实 API
        news_items = await self._fetch_mock_news(category, limit)

        # 去重
        new_items = []
        for item in news_items:
            if item.id not in self._seen_ids:
                self._seen_ids.add(item.id)
                new_items.append(item)
                self._news_cache.append(item)

        # 限制缓存大小
        if len(self._news_cache) > self._max_cache:
            self._news_cache = self._news_cache[-self._max_cache:]

        return new_items

    async def _fetch_mock_news(self, category: str, limit: int) -> list[NewsItem]:
        """模拟新闻数据（后续替换为真实API）。"""
        import random

        mock_news = [
            NewsItem(
                id="n001",
                title="央行宣布降准0.5个百分点，释放长期资金约1万亿",
                summary="央行决定下调金融机构存款准备金率0.5个百分点，预计释放长期资金约1万亿元。",
                category=NewsCategory.POLICY,
                impact=NewsImpact.HIGH,
                source="央行官网",
                key_points=["降准0.5个百分点", "释放约1万亿资金", "利好银行、地产"],
                sentiment="positive",
                related_sectors=["银行", "房地产", "券商"],
            ),
            NewsItem(
                id="n002",
                title="某半导体龙头一季度净利润同比增长120%",
                summary="受益于AI芯片需求爆发，公司一季度营收和利润均超预期。",
                category=NewsCategory.ANNOUNCEMENT,
                impact=NewsImpact.HIGH,
                source="公司公告",
                key_points=["净利润增长120%", "AI芯片需求爆发", "营收超预期"],
                sentiment="positive",
                related_symbols=["芯片龙头"],
                related_sectors=["半导体", "AI"],
            ),
            NewsItem(
                id="n003",
                title="北向资金今日净流入超100亿元",
                summary="北向资金连续5日净流入，外资看好A股后市表现。",
                category=NewsCategory.FINANCE_NEWS,
                impact=NewsImpact.MEDIUM,
                source="沪深港通",
                key_points=["北向资金净流入超100亿", "连续5日净流入"],
                sentiment="positive",
            ),
            NewsItem(
                id="n004",
                title="新能源板块集体走强，光伏龙头涨停",
                summary="受政策利好刺激，新能源板块今日全面走强。",
                category=NewsCategory.SECTOR,
                impact=NewsImpact.MEDIUM,
                source="财经媒体",
                key_points=["新能源板块走强", "光伏龙头涨停", "政策利好"],
                sentiment="positive",
                related_sectors=["新能源", "光伏"],
            ),
            NewsItem(
                id="n005",
                title="国际油价大幅上涨，布伦特原油突破85美元",
                summary="OPEC+减产预期推动国际油价上涨。",
                category=NewsCategory.GLOBAL,
                impact=NewsImpact.MEDIUM,
                source="国际市场",
                key_points=["国际油价上涨", "布伦特原油突破85美元", "OPEC+减产"],
                sentiment="positive",
                related_sectors=["石油", "化工"],
            ),
            NewsItem(
                id="n006",
                title="监管层发文规范量化交易，要求报备策略参数",
                summary="新规要求量化私募报备策略参数，加强对程序化交易的监管。",
                category=NewsCategory.POLICY,
                impact=NewsImpact.MEDIUM,
                source="证监会",
                key_points=["规范量化交易", "报备策略参数", "加强监管"],
                sentiment="neutral",
            ),
            NewsItem(
                id="n007",
                title="多家券商发布4月金股组合，消费和科技成主线",
                summary="券商看好二季度消费复苏和科技成长两条主线。",
                category=NewsCategory.FINANCE_NEWS,
                impact=NewsImpact.LOW,
                source="券商研报",
                key_points=["券商发布金股", "消费和科技成主线"],
                sentiment="positive",
                related_sectors=["消费", "科技"],
            ),
        ]

        result = mock_news
        if category:
            try:
                cat = NewsCategory(category)
                result = [n for n in result if n.category == cat]
            except ValueError:
                pass

        random.shuffle(result)
        return result[:limit]

    # ── Script Generation ───────────────────────────────────────────

    async def _push_news_script(self) -> None:
        """推送新闻口播脚本。"""
        news = self._news_cache[-5:]  # 最近5条
        if not news:
            return

        script = self.generate_script(news)
        bus = await self.bus
        await bus.emit_async("news.script", script.to_dict())

    def generate_script(self, news_items: list[NewsItem]) -> NewsScript:
        """根据新闻列表生成口播脚本。"""
        if not news_items:
            return NewsScript(title="财经新闻", script="今日暂无重大财经新闻。", duration_seconds=15)

        # 按影响程度排序
        sorted_news = sorted(news_items, key=lambda n: (
            -[NewsImpact.HIGH, NewsImpact.MEDIUM, NewsImpact.LOW, NewsImpact.NEUTRAL].index(n.impact),
            -n.published_at,
        ))

        # 只取最重要的3条
        top_news = sorted_news[:3]

        # 生成脚本
        lines = ["来看几条重要的财经新闻。"]
        total_duration = 10

        for i, news in enumerate(top_news, 1):
            duration = 15 if news.impact == NewsImpact.HIGH else 10
            total_duration += duration

            sentiment_word = ""
            if news.sentiment == "positive":
                sentiment_word = "利好"
            elif news.sentiment == "negative":
                sentiment_word = "利空"

            lines.append(
                f"第{i}条，{news.title}。{news.summary}"
                f"{'这对' + '、'.join(news.related_sectors[:2]) + '构成' + sentiment_word + '。' if sentiment_word and news.related_sectors else ''}"
            )

        lines.append("以上是今天的财经新闻速报，具体影响我们后续节目中详细分析。")

        return NewsScript(
            title="财经新闻速报",
            script="。".join(lines),
            duration_seconds=min(total_duration, 60),
            news_items=top_news,
        )

    def summarize(self, content: str, max_length: int = 100) -> str:
        """对长文本进行摘要。"""
        if len(content) <= max_length:
            return content
        # 简单截断 + 省略号
        return content[:max_length - 3] + "..."

    # ── Breaking News ───────────────────────────────────────────────

    async def push_breaking_news(self, title: str, content: str,
                                  impact: NewsImpact = NewsImpact.HIGH) -> None:
        """推送突发新闻。"""
        import hashlib
        news_id = f"breaking_{hashlib.md5(title.encode()).hexdigest()[:8]}"

        if news_id in self._seen_ids:
            return

        item = NewsItem(
            id=news_id,
            title=title,
            summary=content[:100],
            content=content,
            category=NewsCategory.FINANCE_NEWS,
            impact=impact,
            source="突发",
            sentiment="neutral",
        )

        self._seen_ids.add(news_id)
        self._news_cache.append(item)

        bus = await self.bus
        await bus.emit_async("news.breaking", {
            "title": title,
            "content": content,
            "impact": impact.value,
        })

        logger.info("NewsEngine: breaking news — %s", title)

    # ── Query ───────────────────────────────────────────────────────

    def get_latest(self, limit: int = 10) -> list[dict]:
        """获取缓存的最新新闻。"""
        return [n.to_dict() for n in self._news_cache[-limit:]]

    def search(self, keyword: str, limit: int = 10) -> list[dict]:
        """按关键词搜索新闻。"""
        results = []
        for n in self._news_cache:
            if keyword.lower() in n.title.lower() or keyword.lower() in n.summary.lower():
                results.append(n)
                if len(results) >= limit:
                    break
        return [n.to_dict() for n in results]

    def get_stats(self) -> dict:
        return {
            "cached_news": len(self._news_cache),
            "unique_news": len(self._seen_ids),
            "last_fetch": self._last_fetch,
        }
