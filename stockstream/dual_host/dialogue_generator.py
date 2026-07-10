"""Dialogue generator — convert analysis results into natural dual-host scripts.

Transforms structured analysis data into flowing, natural-sounding dialogue
between the veteran trader (male) and finance newcomer (female).
"""

from __future__ import annotations

import random
import logging
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
from stockstream.dual_host.storytelling_engine import StorytellingEngine

logger = logging.getLogger(__name__)


class DialogueGenerator:
    """Generate 3-6 turn dialogues from analysis context."""

    def __init__(
        self,
        emotion_engine: EmotionEngine | None = None,
        storytelling_engine: StorytellingEngine | None = None,
    ) -> None:
        self.emotion = emotion_engine or EmotionEngine()
        self.story = storytelling_engine or StorytellingEngine()

    def generate_stock_dialogue(
        self,
        context: dict[str, Any],
        min_turns: int = 3,
        max_turns: int = 6,
    ) -> DialogueScript:
        """Generate a dialogue about a single stock.

        Flow: Female opens with question → Male analysis → Female follow-up
        → Male deeper insight → Female summary/reaction.

        Args:
            context: Stock analysis context from AnalysisService.
            min_turns: Minimum dialogue turns.
            max_turns: Maximum dialogue turns.

        Returns:
            DialogueScript with 3-6 turns.
        """
        name = context.get("name", "这只股票")
        change_pct = context.get("change_pct", 0) or 0
        try:
            change_pct = float(change_pct)
        except (TypeError, ValueError):
            change_pct = 0

        turns: list[DialogTurn] = []

        # ── Turn 1: Female opening ──────────────────────────────
        opener = self._female_opener(name, change_pct, context)
        turns.append(opener)

        # ── Turn 2: Male analysis with storytelling ─────────────
        analysis_line = self._male_analysis(name, context)
        turns.append(DialogTurn(
            speaker=Speaker.MALE,
            text=analysis_line,
            emotion=self.emotion.detect(analysis_line, Speaker.MALE, context),
        ))

        # ── Turn 3: Female follow-up question ───────────────────
        follow_up = self._female_followup(name, context)
        if follow_up:
            turns.append(DialogTurn(
                speaker=Speaker.FEMALE,
                text=follow_up,
                emotion=Emotion.THINKING,
                is_question=True,
            ))

        # ── Turn 4: Male deeper insight ─────────────────────────
        if len(turns) < max_turns - 1:
            insight = self._male_insight(name, context)
            if insight:
                turns.append(DialogTurn(
                    speaker=Speaker.MALE,
                    text=insight,
                    emotion=self.emotion.detect(insight, Speaker.MALE, context),
                ))

        # ── Turn 5: Female summary ──────────────────────────────
        if len(turns) < max_turns:
            summary = self._female_summary(name, change_pct, context)
            turns.append(DialogTurn(
                speaker=Speaker.FEMALE,
                text=summary,
                emotion=self._summary_emotion(change_pct),
            ))

        # ── Turn 6: Optional extra insight or transition ────────
        if len(turns) < max_turns and random.random() > 0.5:
            extra = self._male_extra(name, context)
            if extra:
                turns.append(DialogTurn(
                    speaker=Speaker.MALE,
                    text=extra,
                    emotion=Emotion.NEUTRAL,
                ))

        segment_id = uuid.uuid4().hex[:8]
        script = DialogueScript(
            segment_id=segment_id,
            segment_type=ShowSegmentType.STOCK_ANALYSIS,
            topic=context.get("symbol", name),
            turns=turns,
        )
        logger.debug("Generated %d-turn dialogue for %s", len(turns), name)
        return script

    def generate_sector_dialogue(
        self,
        context: dict[str, Any],
    ) -> DialogueScript:
        """Generate dialogue about a sector/board."""
        name = context.get("name", context.get("query", "这个板块"))
        turns: list[DialogTurn] = []

        # Female opens
        turns.append(DialogTurn(
            speaker=Speaker.FEMALE,
            text=f"今天{name}板块好热闹啊，到底发生了什么？",
            emotion=Emotion.SURPRISED,
            is_question=True,
        ))

        # Male analysis
        turns.append(DialogTurn(
            speaker=Speaker.MALE,
            text=f"{name}板块今天确实活跃，资金关注度很高。"
                  f"一般来说板块有行情说明有政策或者业绩催化，我们要看看这波是短期炒作还是真正有持续性。",
            emotion=Emotion.NEUTRAL,
        ))

        # Female follow-up
        turns.append(DialogTurn(
            speaker=Speaker.FEMALE,
            text=f"那作为普通投资者，应该怎么参与呢？",
            emotion=Emotion.THINKING,
            is_question=True,
        ))

        # Male insight
        turns.append(DialogTurn(
            speaker=Speaker.MALE,
            text=f"我的建议是做两种准备：如果板块龙头先回调然后回踩不破，可以考虑小仓位试一下；"
                  f"但如果明天就直接高开低走，那就说明是短线资金在出货，别追。",
            emotion=Emotion.SERIOUS,
        ))

        # Female summary
        turns.append(DialogTurn(
            speaker=Speaker.FEMALE,
            text=f"明白了，看龙头、等回调、设止损，听起来很有道理！"
                  f"我们来看看下一只股票。",
            emotion=Emotion.HAPPY,
        ))

        return DialogueScript(
            segment_id=uuid.uuid4().hex[:8],
            segment_type=ShowSegmentType.HOT_SECTOR,
            topic=name,
            turns=turns,
        )

    def generate_market_review(
        self,
        context: dict[str, Any],
    ) -> DialogueScript:
        """Generate a market overview dialogue."""
        up_count = context.get("up_count", 0)
        down_count = context.get("down_count", 0)
        avg_change = context.get("avg_change_pct", 0) or 0

        turns: list[DialogTurn] = []

        # Female opening
        turns.append(DialogTurn(
            speaker=Speaker.FEMALE,
            text="来，我们复盘一下今天整体市场的情况。今天大盘怎么样？",
            emotion=Emotion.NEUTRAL,
            is_question=True,
        ))

        # Male overview
        overview = f"今天市场整体来说，{up_count}家上涨，{down_count}家下跌，"
        try:
            avg_change_f = float(avg_change)
            if avg_change_f > 0:
                overview += f"平均涨幅{avg_change_f:+.2f}%，算是一个偏多的行情。"
            elif avg_change_f < 0:
                overview += f"平均跌幅{avg_change_f:.2f}%，空头占了一些优势。"
            else:
                overview += "多空打了个平手，横盘整理。"
        except (TypeError, ValueError):
            overview += "多空分歧比较大。"
        turns.append(DialogTurn(
            speaker=Speaker.MALE,
            text=overview,
            emotion=Emotion.NEUTRAL,
        ))

        # Female follow-up
        turns.append(DialogTurn(
            speaker=Speaker.FEMALE,
            text="那总结下来，今天最重要的看点是什么？",
            emotion=Emotion.THINKING,
            is_question=True,
        ))

        # Male summary
        turns.append(DialogTurn(
            speaker=Speaker.MALE,
            text="今天的核心关键词就是'结构分化'。有热点也有冷门，"
                  "资金在板块之间快速轮动，说明市场没有形成共识。"
                  "这种行情下追高容易吃亏，还是那句话——控制仓位，耐心等机会。",
            emotion=Emotion.SERIOUS,
        ))

        # Female closing
        turns.append(DialogTurn(
            speaker=Speaker.FEMALE,
            text="好的，今天的复盘就到这里。记住老师说的，仓位管理比选股更重要！"
                  "明天同一时间，我们不见不散~",
            emotion=Emotion.HAPPY,
        ))

        return DialogueScript(
            segment_id=uuid.uuid4().hex[:8],
            segment_type=ShowSegmentType.MARKET_REVIEW,
            topic="market_review",
            turns=turns,
        )

    # ── dialogue line builders ──────────────────────────────────

    def _female_opener(self, name: str, change_pct: float,
                       context: dict) -> DialogTurn:
        """Female host opens the discussion about a stock."""
        try:
            change_pct = float(change_pct)
        except (TypeError, ValueError):
            change_pct = 0

        if change_pct > 5:
            templates = [
                f"哇，{name}今天涨得不错啊！怎么回事，背后有什么大利好吗？",
                f"{name}今天突然拉起来了，发生了什么？",
                f"今天{name}的走势很强势啊，能给我们分析一下吗？",
            ]
        elif change_pct > 0:
            templates = [
                f"{name}今天小幅上涨，这个走势怎么样？",
                f"看看{name}，今天虽然涨得不多但也翻红了，你怎么看？",
            ]
        elif change_pct < -5:
            templates = [
                f"{name}今天跌得有点惨啊，是要出什么问题了吗？",
                f"{name}今天怎么突然崩了？是暴雷还是市场情绪不好？",
                f"哎呀，{name}今天跌了不少，要不要割肉跑路？",
            ]
        elif change_pct < 0:
            templates = [
                f"{name}今天微跌，这个走势你怎么看？",
                f"{name}收跌了，不过幅度不大，要不要关注？",
            ]
        else:
            templates = [
                f"{name}今天没什么动静，你怎么看这只票？",
                f"{name}今天涨跌都不大，是暴风雨前的宁静吗？",
            ]

        return DialogTurn(
            speaker=Speaker.FEMALE,
            text=random.choice(templates),
            emotion=self.emotion.detect(random.choice(templates), Speaker.FEMALE, context),
            is_question=True,
        )

    def _male_analysis(self, name: str, context: dict) -> str:
        """Male host delivers the main analysis with storytelling."""
        stories = self.story.translate_indicators(context)

        change_pct = context.get("change_pct", 0) or 0
        try:
            change_pct = float(change_pct)
        except (TypeError, ValueError):
            change_pct = 0

        parts: list[str] = []

        # Opening line
        if change_pct > 5:
            parts.append(f"{name}今天确实很强，")
        elif change_pct > 0:
            parts.append(f"{name}今天小幅翻红，短期来看，")
        elif change_pct < -5:
            parts.append(f"{name}今天确实是回调幅度比较大，不过我们要客观分析一下，")
        elif change_pct < 0:
            parts.append(f"{name}目前处于调整阶段，")
        else:
            parts.append(f"{name}目前走势比较平稳，")

        # Add stories (indicators in plain language)
        if stories:
            parts.append("。".join(stories[:2]) + "。")
        else:
            parts.append("基本面上没有特别大的变化。")

        return "".join(parts)

    def _female_followup(self, name: str, context: dict) -> str | None:
        """Female asks a follow-up question."""
        change_pct = context.get("change_pct", 0) or 0
        try:
            change_pct = float(change_pct)
        except (TypeError, ValueError):
            change_pct = 0

        inflow = context.get("main_inflow", 0) or 0
        try:
            inflow = float(inflow)
        except (TypeError, ValueError):
            inflow = 0

        if change_pct > 0:
            if inflow > 0:
                return f"那现在追进去还来得及吗？还是等回调再买？"
            return f"这种走势能持续吗？明天会不会又跌回去？"
        elif change_pct < 0:
            if inflow > 0:
                return f"虽然跌了但是资金还在流入？这怎么解释？"
            return f"这个时候适合去抄底吗？还是应该再等等？"
        return f"这种横盘还要盘多久才能选出方向？"

    def _male_insight(self, name: str, context: dict) -> str | None:
        """Male provides deeper insight based on indicators."""
        insights = []
        if context.get("macd_golden_cross"):
            insights.append("MACD金叉刚形成不久，如果下周能放量确认，技术形态会更加健康")
        if context.get("macd_dead_cross"):
            insights.append("MACD刚刚死叉，短期不排除还有调整空间")
        if context.get("shrinking_volume"):
            insights.append("量能比较低迷，没有增量资金进来之前，很难有大行情")

        turnover = context.get("turnover_pct")
        if turnover is not None:
            try:
                if float(turnover) > 8:
                    insights.append("换手率偏高，筹码交换充分，多空双方意见分歧比较大")
            except (TypeError, ValueError):
                pass

        if not insights:
            return None
        return "另外提醒大家，".join(insights[:2])

    def _female_summary(self, name: str, change_pct: float,
                        context: dict) -> str:
        """Female summarizes and transitions."""
        if change_pct > 3:
            return f"好的，{name}目前走势偏强，大家如果想参与的话要做好仓位管理哦。"
        elif change_pct < -3:
            return f"明白了，{name}目前还是回调阶段，现在追进去风险比较大。"
        elif change_pct > 0:
            return f"好，{name}短期还比较稳，可以继续关注。"
        else:
            return f"行，{name}现在先观望，等信号明确了再说。"

    def _male_extra(self, name: str, context: dict) -> str | None:
        """Optional extra insight or transition to next segment."""
        extras = [
            f"总的来说，{name}还是不错的标的，关键是什么时候买和买多少的问题。",
            f"关于{name}就分析到这里，记住，没有永远涨的股票，也没有永远跌的股票。",
            f"投资{name}也好，投别的也好，核心还是要建立自己的交易体系。",
            f"分析归分析，实际操作还是要根据自己的情况来，不要看了直播就冲进去。",
        ]
        return random.choice(extras)

    def _summary_emotion(self, change_pct: float) -> Emotion:
        if change_pct > 3:
            return Emotion.HAPPY
        if change_pct < -3:
            return Emotion.SERIOUS
        return Emotion.NEUTRAL
