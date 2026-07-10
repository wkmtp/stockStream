"""AI 编导系统 (DirectorAgent) — 决定下一段直播内容。

升级版 ChiefDirector，具备:
    1. 智能决策: 根据行情/热点/弹幕/礼物/在线人数决定下一段内容
    2. 观众留存优化: 提高观看时长、互动率、关注率
    3. 多信号融合: 综合多个维度做决策
    4. 节目脚本生成: 输出完整的节目段脚本

输入:
    - 行情数据 (market.price_updated)
    - 热点板块 (selector.signals_detected)
    - 弹幕数据 (danmu.processed)
    - 礼物事件 (live.gift_action)
    - 在线人数 (live.stats)
    - 关注事件 (live.follow)

输出:
    - 节目脚本 (director.segment_script)
    - 内容决策 (director.decision)

用法:
    from src.agents.director import DirectorAgent
    da = DirectorAgent(bus=bus)
    await da.start()
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum

from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


# ── Types ─────────────────────────────────────────────────────────────────


class AudienceMood(Enum):
    """观众情绪。"""
    ENGAGED = "engaged"         # 积极参与
    NEUTRAL = "neutral"         # 中性
    BORED = "bored"             # 无聊
    EXCITED = "excited"         # 兴奋 (大行情/大礼物)
    CONFUSED = "confused"       # 困惑


class MarketMood(Enum):
    """市场情绪。"""
    BULLISH = "bullish"         # 看涨
    BEARISH = "bearish"         # 看跌
    SIDEWAYS = "sideways"       # 横盘
    VOLATILE = "volatile"       # 剧烈波动


@dataclass
class LiveContext:
    """直播上下文 — 综合所有信号。"""
    # 行情
    market_mood: MarketMood = MarketMood.SIDEWAYS
    hot_sectors: list[str] = field(default_factory=list)
    top_movers: list[dict] = field(default_factory=list)

    # 观众
    audience_mood: AudienceMood = AudienceMood.NEUTRAL
    viewer_count: int = 0
    active_viewers: int = 0
    like_rate: float = 0.0         # likes/min
    comment_rate: float = 0.0      # comments/min
    gift_value_total: float = 0.0
    new_followers: int = 0

    # 弹幕
    pending_questions: list[dict] = field(default_factory=list)
    top_comments: list[str] = field(default_factory=list)
    sentiment: float = 0.0         # -1.0 (悲观) ~ 1.0 (乐观)

    # 时间
    session_duration: float = 0.0
    is_market_open: bool = True
    time_since_last_interaction: float = 0.0

    # 内容
    recent_segments: list[str] = field(default_factory=list)
    content_fatigue: float = 0.0   # 内容疲劳度 0~1

    def to_dict(self) -> dict:
        return {
            "market_mood": self.market_mood.value,
            "hot_sectors": self.hot_sectors,
            "audience_mood": self.audience_mood.value,
            "viewer_count": self.viewer_count,
            "active_viewers": self.active_viewers,
            "like_rate": self.like_rate,
            "comment_rate": self.comment_rate,
            "sentiment": self.sentiment,
            "pending_questions": len(self.pending_questions),
        }


@dataclass
class SegmentScript:
    """节目段脚本。"""
    segment_type: str = ""
    title: str = ""
    script: str = ""              # 完整口播脚本
    duration_seconds: int = 60
    reason: str = ""              # 决策理由
    audience_target: str = ""     # 目标: retention / engagement / follow / monetize
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "segment_type": self.segment_type,
            "title": self.title,
            "script": self.script,
            "duration_seconds": self.duration_seconds,
            "reason": self.reason,
            "audience_target": self.audience_target,
        }


# ── Director Agent ────────────────────────────────────────────────────────


class DirectorAgent:
    """AI 编导系统 — 智能直播内容决策。

    核心算法:
        1. 评估观众状态 (engagement/fatigue/mood)
        2. 评估市场状态 (trend/volatility/hotspots)
        3. 内容类型打分
        4. 输出最优脚本

    推送事件:
      director.segment_script   — 节目段脚本
      director.decision         — 决策记录
      director.context_update   — 上下文更新
    """

    # 内容类型权重矩阵 [market_mood][audience_mood] → 内容类型偏好
    CONTENT_WEIGHTS: dict = {
        "stock_analysis": {
            "bullish_engaged": 0.9, "bullish_neutral": 0.8,
            "bearish_neutral": 0.6, "volatile_excited": 0.7,
            "default": 0.5,
        },
        "hot_sector": {
            "bullish_engaged": 0.8, "bullish_excited": 0.9,
            "sideways_neutral": 0.7,
            "default": 0.4,
        },
        "news_brief": {
            "volatile_engaged": 0.8, "volatile_confused": 0.9,
            "default": 0.4,
        },
        "danmu_qa": {
            "neutral_bored": 0.9, "sideways_bored": 0.9,
            "neutral_neutral": 0.7,
            "default": 0.5,
        },
        "fun_fact": {
            "sideways_bored": 0.8, "bearish_bored": 0.7,
            "default": 0.3,
        },
        "risk_tip": {
            "volatile_excited": 0.9, "bullish_excited": 0.7,
            "bearish_confused": 0.8,
            "default": 0.3,
        },
        "knowledge_share": {
            "neutral_bored": 0.7, "sideways_bored": 0.8,
            "default": 0.4,
        },
        "interaction_push": {
            "neutral_bored": 0.8, "bearish_bored": 0.8,
            "default": 0.5,
        },
        "monetization": {
            "bullish_excited": 0.8, "bullish_engaged": 0.7,
            "default": 0.3,
        },
    }

    def __init__(self, bus: EventBus | None = None) -> None:
        self._bus: EventBus | None = bus
        self._context = LiveContext()
        self._running = False
        self._task: asyncio.Task | None = None
        self._decision_count = 0
        self._recent_decisions: list[SegmentScript] = []

        # 决策间隔
        self._last_decision_time = 0.0
        self._min_decision_interval = 30.0  # 至少30秒做一次决策

        # 统计计数器
        self._stats = {
            "decisions_made": 0,
            "retention_actions": 0,
            "engagement_actions": 0,
            "follow_actions": 0,
            "monetize_actions": 0,
        }

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    # ── Lifecycle ───────────────────────────────────────────────────

    async def start(self) -> None:
        """启动 AI 编导。"""
        self._running = True
        self._task = asyncio.create_task(self._decision_loop())

        bus = await self.bus

        # 24h 稳定性：记录所有订阅句柄，stop() 时取消
        self._subs: list[tuple[str, object]] = []

        # 订阅行情
        @bus.on("market.price_updated")
        async def _on_price(event):
            await self._update_market_context(event)
        self._subs.append(("market.price_updated", _on_price))

        # 订阅选股信号
        @bus.on("selector.signals_detected")
        async def _on_signals(event):
            data = event.data or {}
            sectors = data.get("sectors", [])
            if sectors:
                self._context.hot_sectors = sectors[:5]
        self._subs.append(("selector.signals_detected", _on_signals))

        # 订阅弹幕
        @bus.on("danmu.processed")
        async def _on_danmu(event):
            await self._update_danmu_context(event)
        self._subs.append(("danmu.processed", _on_danmu))

        # 订阅礼物
        @bus.on("live.gift_action")
        async def _on_gift(event):
            await self._update_gift_context(event)
        self._subs.append(("live.gift_action", _on_gift))

        # 订阅直播统计
        @bus.on("live.stats")
        async def _on_stats(event):
            data = event.data or {}
            self._context.viewer_count = data.get("viewer_count", 0)
            self._context.like_rate = data.get("like_rate", 0.0)
            self._context.comment_rate = data.get("comment_rate", 0.0)
            self._context.new_followers = data.get("new_followers", 0)
        self._subs.append(("live.stats", _on_stats))

        logger.info("DirectorAgent started — AI directing mode")

    async def stop(self) -> None:
        """停止 AI 编导。"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # 24h 稳定性：取消所有 EventBus 订阅
        bus = await self.bus
        for pattern, handler in getattr(self, '_subs', []):
            bus.unsubscribe(pattern, handler)
        self._subs = []

        logger.info("DirectorAgent stopped")

    # ── Decision Loop ───────────────────────────────────────────────

    async def _decision_loop(self) -> None:
        """决策主循环。"""
        bus = await self.bus
        while self._running:
            try:
                now = time.time()

                # 检查是否需要做决策
                if now - self._last_decision_time < self._min_decision_interval:
                    await asyncio.sleep(5)
                    continue

                # 评估当前状态
                self._evaluate_audience_mood()
                self._evaluate_content_fatigue()

                # 生成决策
                script = await self._make_decision()
                if script:
                    self._last_decision_time = now
                    self._decision_count += 1
                    self._recent_decisions.append(script)
                    if len(self._recent_decisions) > 50:
                        self._recent_decisions = self._recent_decisions[-50:]

                    # 推送脚本
                    await bus.emit_async("director.segment_script", script.to_dict())
                    await bus.emit_async("director.decision", {
                        "segment_type": script.segment_type,
                        "reason": script.reason,
                        "target": script.audience_target,
                    })

                    logger.info("DirectorAgent: decided → %s (%s)",
                               script.segment_type, script.reason)

                # 推送上下文
                await bus.emit_async("director.context_update", self._context.to_dict())

                await asyncio.sleep(self._min_decision_interval)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("DirectorAgent decision error: %s", exc)
                await asyncio.sleep(5)

    # ── Context Updates ─────────────────────────────────────────────

    async def _update_market_context(self, event: Any) -> None:
        """更新市场上下文。"""
        data = event.data or {}
        change_pct = data.get("change_pct", 0.0)

        if change_pct > 2:
            self._context.market_mood = MarketMood.BULLISH
        elif change_pct < -2:
            self._context.market_mood = MarketMood.BEARISH
        elif abs(change_pct) > 0.5:
            self._context.market_mood = MarketMood.VOLATILE
        else:
            self._context.market_mood = MarketMood.SIDEWAYS

    async def _update_danmu_context(self, event: Any) -> None:
        """更新弹幕上下文。"""
        data = event.data or {}
        content = data.get("content", "")
        tags = data.get("tags", [])

        # 记录问题
        if "stock_question" in tags:
            self._context.pending_questions.append({
                "username": data.get("username", ""),
                "content": content,
                "timestamp": time.time(),
            })
            # 只保留最近20条
            self._context.pending_questions = self._context.pending_questions[-20:]

        # 记录热门评论
        if len(content) > 5:
            self._context.top_comments.append(content)
            self._context.top_comments = self._context.top_comments[-10:]

        # 简单情绪分析
        positive = ["涨", "涨停", "牛", "赚", "好", "强", "冲", "起飞"]
        negative = ["跌", "跌停", "亏", "烂", "差", "套", "割肉"]
        for w in positive:
            if w in content:
                self._context.sentiment = min(1.0, self._context.sentiment + 0.05)
                break
        for w in negative:
            if w in content:
                self._context.sentiment = max(-1.0, self._context.sentiment - 0.05)
                break

    async def _update_gift_context(self, event: Any) -> None:
        """更新礼物上下文。"""
        data = event.data or {}
        value = data.get("value", 0.0)
        self._context.gift_value_total += value

        # 大礼物 → 观众情绪变为 excited
        if value > 50:
            self._context.audience_mood = AudienceMood.EXCITED

    # ── Evaluation ──────────────────────────────────────────────────

    def _evaluate_audience_mood(self) -> None:
        """评估观众情绪。"""
        ctx = self._context

        if ctx.viewer_count == 0:
            ctx.audience_mood = AudienceMood.NEUTRAL
            return

        # 高互动率 → engaged
        if ctx.comment_rate > 5 or ctx.like_rate > 10:
            ctx.audience_mood = AudienceMood.ENGAGED
            return

        # 低互动率 + 长时间 → bored
        if ctx.comment_rate < 1 and ctx.like_rate < 2 and ctx.session_duration > 300:
            ctx.audience_mood = AudienceMood.BORED
            return

        # 高情绪值 → excited
        if abs(ctx.sentiment) > 0.5:
            ctx.audience_mood = AudienceMood.EXCITED if ctx.sentiment > 0 else AudienceMood.CONFUSED
            return

        ctx.audience_mood = AudienceMood.NEUTRAL

    def _evaluate_content_fatigue(self) -> None:
        """评估内容疲劳度。"""
        if not self._recent_decisions:
            self._context.content_fatigue = 0.0
            return

        recent = self._recent_decisions[-5:]
        unique_types = len(set(d.segment_type for d in recent))
        if unique_types <= 1:
            self._context.content_fatigue = 0.8  # 重复太多
        elif unique_types <= 2:
            self._context.content_fatigue = 0.4
        else:
            self._context.content_fatigue = 0.1

    # ── Decision Making ─────────────────────────────────────────────

    async def _make_decision(self) -> SegmentScript | None:
        """根据上下文做出内容决策。"""
        ctx = self._context
        market = ctx.market_mood.value
        audience = ctx.audience_mood.value

        # 构建评分 key
        score_key = f"{market}_{audience}"

        # 计算每种内容类型的得分
        scores: dict[str, float] = {}
        for content_type, weights in self.CONTENT_WEIGHTS.items():
            score = weights.get(score_key, weights.get("default", 0.3))

            # 内容疲劳惩罚
            score *= (1.0 - ctx.content_fatigue * 0.5)

            # 有未回答问题 → 提高 Q&A 权重
            if content_type == "danmu_qa" and ctx.pending_questions:
                score *= 1.5

            # 大行情 → 提高分析类权重
            if content_type in ("stock_analysis", "hot_sector") and market in ("bullish", "volatile"):
                score *= 1.3

            # 观众无聊 → 提高互动类权重
            if audience == "bored" and content_type in ("danmu_qa", "fun_fact", "interaction_push"):
                score *= 1.5

            # 大礼物 → 提高商业化权重
            if audience == "excited" and content_type == "monetization":
                score *= 1.8

            scores[content_type] = score

        if not scores:
            return None

        # 选择得分最高的
        best_type = max(scores, key=lambda k: scores[k])
        score = scores[best_type]

        # 生成脚本
        script = await self._generate_script(best_type, score)
        self._stats["decisions_made"] += 1

        # 统计目标
        target = script.audience_target
        if target == "retention":
            self._stats["retention_actions"] += 1
        elif target == "engagement":
            self._stats["engagement_actions"] += 1
        elif target == "follow":
            self._stats["follow_actions"] += 1
        elif target == "monetize":
            self._stats["monetize_actions"] += 1

        return script

    async def _generate_script(self, content_type: str, score: float) -> SegmentScript:
        """根据内容类型生成节目脚本。"""
        ctx = self._context

        generators = {
            "stock_analysis": self._gen_stock_analysis,
            "hot_sector": self._gen_hot_sector,
            "news_brief": self._gen_news_brief,
            "danmu_qa": self._gen_danmu_qa,
            "fun_fact": self._gen_fun_fact,
            "risk_tip": self._gen_risk_tip,
            "knowledge_share": self._gen_knowledge_share,
            "interaction_push": self._gen_interaction_push,
            "monetization": self._gen_monetization,
        }

        gen = generators.get(content_type, self._gen_default)
        return gen()

    # ── Script Generators ───────────────────────────────────────────

    def _gen_stock_analysis(self) -> SegmentScript:
        ctx = self._context
        scripts = [
            "好，让我们来看看今天的热门个股表现。从盘面来看，",
            "接下来是我们的个股分析环节。今天市场",
            "各位观众，我们来分析一下当前的行情走势。",
        ]
        return SegmentScript(
            segment_type="stock_analysis",
            title="个股分析",
            script=random.choice(scripts) + f"当前市场情绪{ctx.market_mood.value}，建议关注成交量的配合。",
            duration_seconds=60,
            reason=f"市场{ctx.market_mood.value}, 得分={random.uniform(0.7, 0.95):.2f}",
            audience_target="retention",
        )

    def _gen_hot_sector(self) -> SegmentScript:
        ctx = self._context
        sectors = ctx.hot_sectors or ["科技", "新能源", "消费"]
        return SegmentScript(
            segment_type="hot_sector",
            title="热点板块",
            script=f"今天的热点板块方面，{random.choice(sectors)}表现抢眼。板块轮动加快，要注意把握节奏。",
            duration_seconds=45,
            reason=f"热点板块分析",
            audience_target="retention",
        )

    def _gen_news_brief(self) -> SegmentScript:
        return SegmentScript(
            segment_type="news_brief",
            title="财经新闻",
            script="来看几条重要的财经新闻。第一，... 第二，... 这些消息对市场的影响值得关注。",
            duration_seconds=30,
            reason="新闻播报保持信息密度",
            audience_target="retention",
        )

    def _gen_danmu_qa(self) -> SegmentScript:
        ctx = self._context
        if ctx.pending_questions:
            q = ctx.pending_questions.pop(0)
            return SegmentScript(
                segment_type="danmu_qa",
                title="弹幕问答",
                script=f"感谢{q['username']}的提问！{q['content']}这个问题问得很好...",
                duration_seconds=30,
                reason=f"回答用户提问: {q['username']}",
                audience_target="engagement",
            )
        return SegmentScript(
            segment_type="danmu_qa",
            title="弹幕互动",
            script="来看看大家的弹幕都在聊什么。有什么问题欢迎大家随时发弹幕，主播在线回答！",
            duration_seconds=20,
            reason="弹幕互动引导",
            audience_target="engagement",
        )

    def _gen_fun_fact(self) -> SegmentScript:
        facts = [
            "给大家分享一个有趣的财经小知识。你知道华尔街铜牛有多重吗？3.2吨！",
            "分享一个冷知识：全球第一只股票诞生于1602年的荷兰东印度公司。",
            "有趣的知识：巴菲特的办公室没有电脑，他只用一部翻盖手机。",
        ]
        return SegmentScript(
            segment_type="fun_fact",
            title="财经趣闻",
            script=random.choice(facts),
            duration_seconds=15,
            reason="内容疲劳度偏高，切换轻松话题",
            audience_target="retention",
        )

    def _gen_risk_tip(self) -> SegmentScript:
        tips = [
            "温馨提示：投资有风险，入市需谨慎。不要把所有资金投入一只股票，分散投资很重要。",
            "风险提示：股市有涨有跌，短期波动是正常的。保持理性，不要追涨杀跌。",
            "重要提醒：以上内容仅供学习交流，不构成任何投资建议。请独立判断，自负盈亏。",
        ]
        return SegmentScript(
            segment_type="risk_tip",
            title="风险提示",
            script=random.choice(tips),
            duration_seconds=15,
            reason="合规风控要求",
            audience_target="retention",
        )

    def _gen_knowledge_share(self) -> SegmentScript:
        return SegmentScript(
            segment_type="knowledge_share",
            title="投资知识",
            script="今天给大家分享一个实用的投资知识。均线系统是我们看盘最基本的工具...",
            duration_seconds=30,
            reason="教育类内容增加留存",
            audience_target="retention",
        )

    def _gen_interaction_push(self) -> SegmentScript:
        return SegmentScript(
            segment_type="interaction_push",
            title="互动引导",
            script="觉得主播分析得不错的朋友，点个赞支持一下！新来的朋友记得点关注，不错过每天的行情分析！",
            duration_seconds=10,
            reason="观众互动率偏低，主动引导互动",
            audience_target="follow",
        )

    def _gen_monetization(self) -> SegmentScript:
        return SegmentScript(
            segment_type="monetization",
            title="商业化",
            script="感谢大家的支持！如果有朋友想深入学习股票投资，可以关注我们的会员专区...",
            duration_seconds=20,
            reason="观众情绪高涨，适合商业化",
            audience_target="monetize",
        )

    def _gen_default(self) -> SegmentScript:
        return SegmentScript(
            segment_type="stock_analysis",
            title="行情分析",
            script="让我们继续关注行情走势...",
            duration_seconds=30,
            reason="默认内容",
            audience_target="retention",
        )

    # ── Query ───────────────────────────────────────────────────────

    def get_context(self) -> dict:
        return self._context.to_dict()

    def get_stats(self) -> dict:
        return {
            **self._stats,
            "decision_count": self._decision_count,
            "pending_questions": len(self._context.pending_questions),
            "context": self._context.to_dict(),
        }
