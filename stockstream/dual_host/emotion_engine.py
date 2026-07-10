"""Emotion engine — detects the right emotion for each dialogue line.

Analyses text content, numerical data, and speaker role to determine
the optimal emotional tone for TTS synthesis.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from stockstream.dual_host.models import Emotion, Speaker

logger = logging.getLogger(__name__)

# ── Keyword → emotion mapping ──────────────────────────────────

_EMOTION_KEYWORDS: dict[Emotion, list[str]] = {
    Emotion.EXCITED: [
        "涨停", "涨停板", "暴涨", "飙升", "狂飙", "领涨", "大涨",
        "涨幅", "突破新高", "强势封板", "历史新高", "涨幅惊人",
        "打板", "封板", "大阳线", "放量突破",
    ],
    Emotion.HAPPY: [
        "上涨", "收红", "飘红", "翻红", "走强", "反弹", "回升",
        "净流入", "资金流入", "主力流入", "大幅流入", "流入",
        "加仓", "增持", "利好", "政策利好", "业绩增长", "回购", "分红",
        "抄底成功", "吃肉", "赚了",
    ],
    Emotion.SURPRISED: [
        "突然", "意外", "猛拉", "跳水", "闪崩", "竟", "罕见",
        "没想到", "反转", "逆势", "逆天", "惊天",
        "天地板", "地天板", "怪异", "没想到"
    ],
    Emotion.WARNING: [
        "下跌", "跌幅", "大跌", "暴跌", "重挫", "回调",
        "净流出", "资金流出", "主力出逃", "减持", "清仓",
        "风险", "利空", "亏损", "退市", "ST", "暴雷",
        "追高", "套牢", "被套", "割肉", "止损",
        "量能不足", "破位", "跌破", "死叉",
    ],
    Emotion.SERIOUS: [
        "注意", "注意风险", "风险控制", "提醒", "警惕", "谨慎", "观望", "等待",
        "不适合追涨", "控制仓位", "基本面",
        "政策", "监管", "警惕", "估值", "泡沫",
        "分析", "数据", "报告", "统计",
    ],
    Emotion.THINKING: [
        "但是", "不过", "然而", "从另一方面", "换个角度看",
        "需要考虑", "需要关注", "值得注意", "也许", "可能",
        "未必", "不一定", "会不会", "是不是",
    ],
}

# ── Punctuation → emotion bias ─────────────────────────────────

_EXCLAMATION_EMOTIONS = [Emotion.EXCITED, Emotion.SURPRISED]
_QUESTION_EMOTIONS = [Emotion.THINKING, Emotion.SURPRISED]
_ELLIPSIS_EMOTIONS = [Emotion.THINKING, Emotion.SERIOUS]


class EmotionEngine:
    """Infer emotion from text content and market context."""

    def detect(self, text: str, speaker: Speaker,
               context: dict[str, Any] | None = None) -> Emotion:
        """Detect the dominant emotion for a given text and speaker.

        Args:
            text: The spoken text.
            speaker: Who is speaking.
            context: Optional market context (change_pct, inflow, etc).

        Returns:
            Best-fit Emotion enum.
        """
        text = text.strip()

        # 1. Check context-based signals (strongest)
        ctx_emotion = self._from_context(context)
        if ctx_emotion and ctx_emotion != Emotion.NEUTRAL:
            return ctx_emotion

        # 2. Keyword matching
        kw_emotion = self._from_keywords(text)
        if kw_emotion:
            return kw_emotion

        # 3. Punctuation hints
        punct_emotion = self._from_punctuation(text, speaker)
        if punct_emotion:
            return punct_emotion

        # 4. Speaker default
        return self._speaker_default(speaker)

    def batch_detect(self, lines: list[str], speaker: Speaker,
                     contexts: list[dict[str, Any] | None] | None = None) -> list[Emotion]:
        """Detect emotions for a batch of lines."""
        if contexts is None:
            contexts = [None] * len(lines)
        return [self.detect(line, speaker, ctx) for line, ctx in zip(lines, contexts)]

    # ── detectors ──────────────────────────────────────────────

    def _from_context(self, context: dict[str, Any] | None) -> Emotion | None:
        if not context:
            return None

        change_pct = context.get("change_pct", 0) or 0
        try:
            change_pct = float(change_pct)
        except (TypeError, ValueError):
            change_pct = 0

        if change_pct >= 9.5:
            return Emotion.EXCITED
        if change_pct >= 5:
            return Emotion.HAPPY
        if change_pct >= 3:
            return Emotion.HAPPY
        if change_pct <= -9.5:
            return Emotion.WARNING
        if change_pct <= -5:
            return Emotion.WARNING
        if change_pct <= -3:
            return Emotion.SERIOUS

        inflow = context.get("main_inflow", 0) or 0
        try:
            inflow = float(inflow)
        except (TypeError, ValueError):
            inflow = 0

        if inflow > 1e8:
            return Emotion.HAPPY
        if inflow < -1e8:
            return Emotion.WARNING

        if context.get("macd_golden_cross"):
            return Emotion.HAPPY
        if context.get("macd_dead_cross"):
            return Emotion.SERIOUS

        return None

    def _from_keywords(self, text: str) -> Emotion | None:
        """Match text against keyword patterns, ranking by match count then priority."""
        matched: dict[Emotion, int] = {}
        for emotion, keywords in _EMOTION_KEYWORDS.items():
            count = sum(1 for kw in keywords if kw in text)
            if count:
                matched[emotion] = count

        if not matched:
            return None

        # Primary: highest keyword match count; secondary: priority order
        max_count = max(matched.values())
        candidates = [em for em, c in matched.items() if c == max_count]
        if len(candidates) == 1:
            return candidates[0]

        priority_order = [Emotion.EXCITED, Emotion.SURPRISED, Emotion.WARNING,
                          Emotion.HAPPY, Emotion.SERIOUS, Emotion.THINKING]
        for em in priority_order:
            if em in candidates:
                return em
        return candidates[0]

    def _from_punctuation(self, text: str, speaker: Speaker) -> Emotion | None:
        if "！" in text or "!!" in text:
            if speaker == Speaker.FEMALE:
                return Emotion.SURPRISED
            return Emotion.EXCITED
        if "？" in text or "??" in text:
            if speaker == Speaker.FEMALE:
                return Emotion.THINKING
            return Emotion.THINKING
        if "..." in text or "…" in text:
            return Emotion.THINKING
        return None

    def _speaker_default(self, speaker: Speaker) -> Emotion:
        if speaker == Speaker.MALE:
            return Emotion.NEUTRAL
        return Emotion.HAPPY
