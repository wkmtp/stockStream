"""Data models for content_scene_matcher.

Defines:
    IndicatorCategory  — coarse indicator grouping (MACD, RSI, VOLUME, FUND_FLOW, etc.)
    MatchedIndicator   — a single detected indicator with confidence
    MatchResult        — full analysis result: detected indicators + recommended scene
    KEYWORD_MAP        — keyword → (IndicatorCategory, weight) mapping table
    PATTERN_MAP        — regex pattern → (IndicatorCategory, weight) mapping table
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from stockstream.video.scene_manager import SceneType


# ── indicator category ─────────────────────────────────────────────────────

class IndicatorCategory(str, Enum):
    """Coarse indicator categories detected from commentary text."""

    MACD = "MACD"                # MACD 金叉/死叉/背离
    RSI = "RSI"                  # RSI 超买/超卖
    VOLUME = "VOLUME"            # 成交量 / 放量 / 缩量 / 换手率
    FUND_FLOW = "FUND_FLOW"      # 资金流向 / 主力 / 北向
    KLINE = "KLINE"              # K线 / 走势 / 趋势 / 均线
    INTRADAY = "INTRADAY"        # 分时 / 盘中 / 日内
    SECTOR = "SECTOR"            # 板块 / 行业 / 概念
    DRAGON_TIGER = "DRAGON_TIGER"  # 龙虎榜 / 营业部 / 席位
    ADVANCE_DECLINE = "ADVANCE_DECLINE"  # 涨跌家数 / 市场情绪
    AI_SUMMARY = "AI_SUMMARY"    # AI 分析 / 总结 / 后市展望

    @property
    def label(self) -> str:
        _labels = {
            IndicatorCategory.MACD: "MACD 指标",
            IndicatorCategory.RSI: "RSI 指标",
            IndicatorCategory.VOLUME: "成交量",
            IndicatorCategory.FUND_FLOW: "资金流向",
            IndicatorCategory.KLINE: "K线趋势",
            IndicatorCategory.INTRADAY: "分时走势",
            IndicatorCategory.SECTOR: "板块分析",
            IndicatorCategory.DRAGON_TIGER: "龙虎榜",
            IndicatorCategory.ADVANCE_DECLINE: "涨跌统计",
            IndicatorCategory.AI_SUMMARY: "AI 摘要",
        }
        return _labels.get(self, self.value)


# ── Category → SceneType mapping ───────────────────────────────────────────

CATEGORY_SCENE_MAP: dict[IndicatorCategory, SceneType] = {
    IndicatorCategory.MACD: SceneType.MACD,
    IndicatorCategory.RSI: SceneType.RSI,
    IndicatorCategory.VOLUME: SceneType.VOLUME,
    IndicatorCategory.FUND_FLOW: SceneType.FUND_FLOW,
    IndicatorCategory.KLINE: SceneType.KLINE,
    IndicatorCategory.INTRADAY: SceneType.MINUTE,
    IndicatorCategory.SECTOR: SceneType.SECTOR_HEATMAP,
    IndicatorCategory.DRAGON_TIGER: SceneType.DRAGON_TIGER,
    IndicatorCategory.ADVANCE_DECLINE: SceneType.ADVANCE_DECLINE,
    IndicatorCategory.AI_SUMMARY: SceneType.AI_SUMMARY,
}


# ── keyword mapping table ──────────────────────────────────────────────────

# (keyword, category, weight)
# weight ∈ [0.3, 2.0]: higher weight = stronger signal
KEYWORD_MAP: list[tuple[str, IndicatorCategory, float]] = [
    # ── MACD ──────────────────────────────────────────────────────────
    ("MACD金叉", IndicatorCategory.MACD, 2.0),
    ("MACD死叉", IndicatorCategory.MACD, 2.0),
    ("macd金叉", IndicatorCategory.MACD, 2.0),
    ("macd死叉", IndicatorCategory.MACD, 2.0),
    ("金叉", IndicatorCategory.MACD, 1.8),
    ("死叉", IndicatorCategory.MACD, 1.8),
    ("MACD", IndicatorCategory.MACD, 1.5),
    ("macd", IndicatorCategory.MACD, 1.5),
    ("底背离", IndicatorCategory.MACD, 1.5),
    ("顶背离", IndicatorCategory.MACD, 1.5),
    ("DIF", IndicatorCategory.MACD, 1.2),
    ("DEA", IndicatorCategory.MACD, 1.2),
    ("dif", IndicatorCategory.MACD, 1.2),
    ("dea", IndicatorCategory.MACD, 1.2),
    ("柱状线", IndicatorCategory.MACD, 0.8),
    ("macd柱", IndicatorCategory.MACD, 0.8),

    # ── RSI ───────────────────────────────────────────────────────────
    ("RSI超买", IndicatorCategory.RSI, 2.0),
    ("RSI超卖", IndicatorCategory.RSI, 2.0),
    ("rsi超买", IndicatorCategory.RSI, 2.0),
    ("rsi超卖", IndicatorCategory.RSI, 2.0),
    ("超买", IndicatorCategory.RSI, 1.8),
    ("超卖", IndicatorCategory.RSI, 1.8),
    ("RSI", IndicatorCategory.RSI, 1.5),
    ("rsi", IndicatorCategory.RSI, 1.5),
    ("相对强弱", IndicatorCategory.RSI, 1.2),
    ("RSI指标", IndicatorCategory.RSI, 1.0),
    ("rsi指标", IndicatorCategory.RSI, 1.0),

    # ── VOLUME ────────────────────────────────────────────────────────
    ("放量上涨", IndicatorCategory.VOLUME, 2.0),
    ("放量下跌", IndicatorCategory.VOLUME, 2.0),
    ("缩量下跌", IndicatorCategory.VOLUME, 2.0),
    ("缩量上涨", IndicatorCategory.VOLUME, 2.0),
    ("量价齐升", IndicatorCategory.VOLUME, 2.0),
    ("量价背离", IndicatorCategory.VOLUME, 2.0),
    ("放量", IndicatorCategory.VOLUME, 1.8),
    ("缩量", IndicatorCategory.VOLUME, 1.8),
    ("天量", IndicatorCategory.VOLUME, 1.8),
    ("地量", IndicatorCategory.VOLUME, 1.8),
    ("成交量", IndicatorCategory.VOLUME, 1.5),
    ("成交额", IndicatorCategory.VOLUME, 1.2),
    ("换手率", IndicatorCategory.VOLUME, 1.5),
    ("换手", IndicatorCategory.VOLUME, 1.2),
    ("量能", IndicatorCategory.VOLUME, 1.2),
    ("成交活跃", IndicatorCategory.VOLUME, 1.2),
    ("成交低迷", IndicatorCategory.VOLUME, 1.2),

    # ── FUND_FLOW ─────────────────────────────────────────────────────
    ("资金流入", IndicatorCategory.FUND_FLOW, 2.0),
    ("资金流出", IndicatorCategory.FUND_FLOW, 2.0),
    ("资金净流入", IndicatorCategory.FUND_FLOW, 2.0),
    ("资金净流出", IndicatorCategory.FUND_FLOW, 2.0),
    ("主力资金", IndicatorCategory.FUND_FLOW, 1.8),
    ("主力净流入", IndicatorCategory.FUND_FLOW, 2.0),
    ("主力净流出", IndicatorCategory.FUND_FLOW, 2.0),
    ("主力进场", IndicatorCategory.FUND_FLOW, 1.8),
    ("主力出逃", IndicatorCategory.FUND_FLOW, 1.8),
    ("主力加仓", IndicatorCategory.FUND_FLOW, 1.8),
    ("主力减仓", IndicatorCategory.FUND_FLOW, 1.8),
    ("资金流向", IndicatorCategory.FUND_FLOW, 1.5),
    ("超大单", IndicatorCategory.FUND_FLOW, 1.2),
    ("大单净", IndicatorCategory.FUND_FLOW, 1.2),
    ("中单净", IndicatorCategory.FUND_FLOW, 1.0),
    ("小单净", IndicatorCategory.FUND_FLOW, 1.0),
    ("北向资金", IndicatorCategory.FUND_FLOW, 1.5),
    ("北向流入", IndicatorCategory.FUND_FLOW, 1.5),
    ("北向流出", IndicatorCategory.FUND_FLOW, 1.5),
    ("资金面", IndicatorCategory.FUND_FLOW, 1.0),
    ("大资金", IndicatorCategory.FUND_FLOW, 1.2),
    ("机构资金", IndicatorCategory.FUND_FLOW, 1.2),
    ("游资", IndicatorCategory.FUND_FLOW, 1.0),
    ("净流入", IndicatorCategory.FUND_FLOW, 1.5),
    ("净流出", IndicatorCategory.FUND_FLOW, 1.5),

    # ── KLINE ─────────────────────────────────────────────────────────
    ("K线", IndicatorCategory.KLINE, 1.5),
    ("走势", IndicatorCategory.KLINE, 1.0),
    ("行情", IndicatorCategory.KLINE, 1.0),
    ("趋势", IndicatorCategory.KLINE, 1.2),
    ("均线", IndicatorCategory.KLINE, 1.5),
    ("突破", IndicatorCategory.KLINE, 1.2),
    ("回踩", IndicatorCategory.KLINE, 1.2),
    ("支撑", IndicatorCategory.KLINE, 1.2),
    ("压力", IndicatorCategory.KLINE, 1.2),
    ("上涨", IndicatorCategory.KLINE, 0.8),
    ("下跌", IndicatorCategory.KLINE, 0.8),
    ("涨停", IndicatorCategory.KLINE, 1.0),
    ("跌停", IndicatorCategory.KLINE, 1.0),
    ("反弹", IndicatorCategory.KLINE, 1.0),
    ("回调", IndicatorCategory.KLINE, 1.0),
    ("新高", IndicatorCategory.KLINE, 1.0),
    ("新低", IndicatorCategory.KLINE, 1.0),
    ("多头", IndicatorCategory.KLINE, 1.0),
    ("空头", IndicatorCategory.KLINE, 1.0),
    ("阳线", IndicatorCategory.KLINE, 1.2),
    ("阴线", IndicatorCategory.KLINE, 1.2),
    ("MA5", IndicatorCategory.KLINE, 1.0),
    ("MA10", IndicatorCategory.KLINE, 1.0),
    ("MA20", IndicatorCategory.KLINE, 1.0),
    ("MA60", IndicatorCategory.KLINE, 1.0),
    ("布林带", IndicatorCategory.KLINE, 1.0),
    ("BOLL", IndicatorCategory.KLINE, 1.0),
    ("日K", IndicatorCategory.KLINE, 1.0),

    # ── INTRADAY ──────────────────────────────────────────────────────
    ("分时图", IndicatorCategory.INTRADAY, 1.5),
    ("分时", IndicatorCategory.INTRADAY, 1.5),
    ("盘中", IndicatorCategory.INTRADAY, 1.5),
    ("日内", IndicatorCategory.INTRADAY, 1.5),
    ("开盘", IndicatorCategory.INTRADAY, 1.2),
    ("午盘", IndicatorCategory.INTRADAY, 1.2),
    ("尾盘", IndicatorCategory.INTRADAY, 1.2),
    ("收盘", IndicatorCategory.INTRADAY, 1.0),
    ("盘中拉升", IndicatorCategory.INTRADAY, 1.5),
    ("尾盘跳水", IndicatorCategory.INTRADAY, 1.5),
    ("早盘", IndicatorCategory.INTRADAY, 1.2),
    ("盘中异动", IndicatorCategory.INTRADAY, 1.5),
    ("盘中走势", IndicatorCategory.INTRADAY, 1.2),
    ("日内波动", IndicatorCategory.INTRADAY, 1.2),
    ("盘中震荡", IndicatorCategory.INTRADAY, 1.2),
    ("60分钟", IndicatorCategory.INTRADAY, 1.0),

    # ── SECTOR ────────────────────────────────────────────────────────
    ("板块", IndicatorCategory.SECTOR, 1.2),
    ("行业", IndicatorCategory.SECTOR, 1.0),
    ("概念", IndicatorCategory.SECTOR, 0.8),
    ("板块轮动", IndicatorCategory.SECTOR, 1.5),
    ("领涨板块", IndicatorCategory.SECTOR, 1.5),
    ("领跌板块", IndicatorCategory.SECTOR, 1.5),
    ("热点板块", IndicatorCategory.SECTOR, 1.5),
    ("热力图", IndicatorCategory.SECTOR, 1.2),
    ("板块涨幅", IndicatorCategory.SECTOR, 1.2),
    ("板块跌幅", IndicatorCategory.SECTOR, 1.2),
    ("板块活跃", IndicatorCategory.SECTOR, 1.2),
    ("白酒板块", IndicatorCategory.SECTOR, 1.5),
    ("新能源板块", IndicatorCategory.SECTOR, 1.5),
    ("半导体板块", IndicatorCategory.SECTOR, 1.5),
    ("AI板块", IndicatorCategory.SECTOR, 1.5),
    ("芯片板块", IndicatorCategory.SECTOR, 1.5),
    ("医药板块", IndicatorCategory.SECTOR, 1.5),
    ("消费板块", IndicatorCategory.SECTOR, 1.5),
    ("金融板块", IndicatorCategory.SECTOR, 1.5),
    ("地产板块", IndicatorCategory.SECTOR, 1.5),
    ("军工板块", IndicatorCategory.SECTOR, 1.5),
    ("光伏板块", IndicatorCategory.SECTOR, 1.5),
    ("汽车板块", IndicatorCategory.SECTOR, 1.5),
    ("煤炭板块", IndicatorCategory.SECTOR, 1.5),
    ("有色板块", IndicatorCategory.SECTOR, 1.5),

    # ── DRAGON_TIGER ──────────────────────────────────────────────────
    ("龙虎榜", IndicatorCategory.DRAGON_TIGER, 1.8),
    ("龙虎", IndicatorCategory.DRAGON_TIGER, 1.5),
    ("上榜", IndicatorCategory.DRAGON_TIGER, 1.0),
    ("营业部", IndicatorCategory.DRAGON_TIGER, 1.5),
    ("席位", IndicatorCategory.DRAGON_TIGER, 1.2),
    ("游资席位", IndicatorCategory.DRAGON_TIGER, 1.5),
    ("机构专用", IndicatorCategory.DRAGON_TIGER, 1.5),
    ("知名游资", IndicatorCategory.DRAGON_TIGER, 1.5),
    ("龙虎榜净买入", IndicatorCategory.DRAGON_TIGER, 1.8),
    ("龙虎榜净卖出", IndicatorCategory.DRAGON_TIGER, 1.8),

    # ── ADVANCE_DECLINE ───────────────────────────────────────────────
    ("涨跌家数", IndicatorCategory.ADVANCE_DECLINE, 1.8),
    ("涨跌比", IndicatorCategory.ADVANCE_DECLINE, 1.8),
    ("涨多跌少", IndicatorCategory.ADVANCE_DECLINE, 1.5),
    ("跌多涨少", IndicatorCategory.ADVANCE_DECLINE, 1.5),
    ("普涨", IndicatorCategory.ADVANCE_DECLINE, 1.8),
    ("普跌", IndicatorCategory.ADVANCE_DECLINE, 1.8),
    ("上涨家数", IndicatorCategory.ADVANCE_DECLINE, 1.5),
    ("下跌家数", IndicatorCategory.ADVANCE_DECLINE, 1.5),
    ("涨停家数", IndicatorCategory.ADVANCE_DECLINE, 1.2),
    ("跌停家数", IndicatorCategory.ADVANCE_DECLINE, 1.2),
    ("市场情绪", IndicatorCategory.ADVANCE_DECLINE, 1.5),
    ("赚钱效应", IndicatorCategory.ADVANCE_DECLINE, 1.5),
    ("市场热度", IndicatorCategory.ADVANCE_DECLINE, 1.2),

    # ── AI_SUMMARY ────────────────────────────────────────────────────
    ("AI分析", IndicatorCategory.AI_SUMMARY, 1.5),
    ("AI总结", IndicatorCategory.AI_SUMMARY, 1.5),
    ("智能分析", IndicatorCategory.AI_SUMMARY, 1.5),
    ("综合研判", IndicatorCategory.AI_SUMMARY, 1.2),
    ("后市", IndicatorCategory.AI_SUMMARY, 1.2),
    ("展望", IndicatorCategory.AI_SUMMARY, 1.0),
    ("预判", IndicatorCategory.AI_SUMMARY, 1.2),
    ("投资建议", IndicatorCategory.AI_SUMMARY, 1.2),
    ("操作建议", IndicatorCategory.AI_SUMMARY, 1.2),
    ("风险提示", IndicatorCategory.AI_SUMMARY, 1.0),
    ("估值", IndicatorCategory.AI_SUMMARY, 1.0),
    ("基本面", IndicatorCategory.AI_SUMMARY, 1.2),
    ("分析", IndicatorCategory.AI_SUMMARY, 0.5),  # low weight, generic
    ("总结", IndicatorCategory.AI_SUMMARY, 0.5),
    ("观点", IndicatorCategory.AI_SUMMARY, 0.5),
    ("建议", IndicatorCategory.AI_SUMMARY, 0.5),
    ("策略", IndicatorCategory.AI_SUMMARY, 0.5),
]

# ── regex pattern mapping table ────────────────────────────────────────────

PATTERN_MAP: list[tuple[str, IndicatorCategory, float]] = [
    # MACD patterns
    (r"(?i)\bmacd\b", IndicatorCategory.MACD, 2.0),
    (r"金叉|死叉", IndicatorCategory.MACD, 2.0),
    (r"(?:底背离|顶背离)", IndicatorCategory.MACD, 1.8),

    # RSI patterns
    (r"(?i)\brsi\b", IndicatorCategory.RSI, 2.0),
    (r"超买|超卖", IndicatorCategory.RSI, 1.8),

    # Volume patterns
    (r"(?:成交|量能|换手)", IndicatorCategory.VOLUME, 1.5),
    (r"放量|缩量|地量|天量", IndicatorCategory.VOLUME, 1.8),
    (r"量价(?:齐升|背离)", IndicatorCategory.VOLUME, 2.0),

    # Fund flow patterns
    (r"主力.*(?:流入|流出|进场|出逃|加仓|减仓|资金)", IndicatorCategory.FUND_FLOW, 2.0),
    (r"(?:北向|外资|机构|游资).*(?:流入|流出|买入|卖出)", IndicatorCategory.FUND_FLOW, 1.8),
    (r"资金.*(?:净流入|净流出|流入|流出)", IndicatorCategory.FUND_FLOW, 1.8),

    # K-line patterns
    (r"K线|走势|行情|趋势|均线|突破|回踩|支撑|压力", IndicatorCategory.KLINE, 1.2),

    # Intraday patterns
    (r"分时|盘中|日内|开盘|午盘|尾盘|早盘", IndicatorCategory.INTRADAY, 1.5),

    # Sector patterns
    (r"(?:白酒|新能源|半导体|AI|芯片|医药|消费|金融|地产|军工|光伏|汽车|煤炭|有色)\s*板块",
     IndicatorCategory.SECTOR, 1.8),
    (r"板块.*(?:表现|涨幅|跌幅|轮动|活跃|拉升|走强|走弱)", IndicatorCategory.SECTOR, 1.5),
    (r"(?:领涨|领跌|热点).*板块", IndicatorCategory.SECTOR, 1.5),

    # Dragon-tiger patterns
    (r"龙虎榜|龙虎", IndicatorCategory.DRAGON_TIGER, 1.8),
    (r"营业部|席位", IndicatorCategory.DRAGON_TIGER, 1.5),
    (r"(?:机构|游资).*(?:专用|买入|卖出)", IndicatorCategory.DRAGON_TIGER, 1.5),

    # Advance/decline patterns
    (r"涨跌.*(?:家数|比)", IndicatorCategory.ADVANCE_DECLINE, 1.8),
    (r"(?:上涨|下跌|涨停|跌停).*家数", IndicatorCategory.ADVANCE_DECLINE, 1.5),
    (r"(?:普涨|普跌)", IndicatorCategory.ADVANCE_DECLINE, 1.8),
    (r"赚钱效应", IndicatorCategory.ADVANCE_DECLINE, 1.5),

    # AI summary patterns
    (r"(?:AI|智能).*(?:分析|总结|研判)", IndicatorCategory.AI_SUMMARY, 1.5),
    (r"(?:后市|展望|预判)", IndicatorCategory.AI_SUMMARY, 1.2),
]

# Compile regex patterns eagerly
for i, (pat, cat, weight) in enumerate(PATTERN_MAP):
    PATTERN_MAP[i] = (pat, cat, weight)  # keep original, compile on demand


# ── reverse index: SceneType → keywords ────────────────────────────────────

def _build_keywords_by_scene() -> dict[SceneType, list[str]]:
    """Build a reverse lookup: SceneType → list of triggering keywords."""
    result: dict[SceneType, list[str]] = {s: [] for s in SceneType}
    for kw, cat, _weight in KEYWORD_MAP:
        st = CATEGORY_SCENE_MAP.get(cat)
        if st and kw not in result[st]:
            result[st].append(kw)
    return result


ALL_KEYWORDS_BY_SCENE: dict[SceneType, list[str]] = _build_keywords_by_scene()


# ── match result dataclasses ───────────────────────────────────────────────

@dataclass()
class MatchedIndicator:
    """A single detected indicator from the commentary text."""

    category: IndicatorCategory
    confidence: float              # 0.0–1.0
    matched_keywords: list[str] = field(default_factory=list)
    matched_patterns: list[str] = field(default_factory=list)

    @property
    def scene_type(self) -> SceneType:
        """Map to the corresponding SceneType."""
        return CATEGORY_SCENE_MAP.get(self.category, SceneType.KLINE)

    @property
    def label(self) -> str:
        return self.category.label


@dataclass()
class MatchResult:
    """Full analysis result for a commentary text.

    Contains:
        - All detected indicators ranked by confidence
        - The recommended best scene_type
        - Whether the scene_manager was notified (switched)
        - Debug info: original text, timing
    """

    text: str
    indicators: list[MatchedIndicator] = field(default_factory=list)
    best_scene: SceneType = SceneType.KLINE
    best_confidence: float = 0.0
    switched: bool = False
    error: Optional[str] = None

    @property
    def best_indicator(self) -> Optional[MatchedIndicator]:
        if self.indicators:
            return self.indicators[0]
        return None

    @property
    def best_label(self) -> str:
        return self.best_scene.label

    @property
    def indicator_labels(self) -> list[str]:
        return [ind.label for ind in self.indicators]

    def to_dict(self) -> dict:
        return {
            "text": self.text[:200],
            "best_scene": self.best_scene.value,
            "best_scene_label": self.best_label,
            "best_confidence": round(self.best_confidence, 4),
            "switched": self.switched,
            "indicators": [
                {
                    "category": ind.category.value,
                    "label": ind.label,
                    "confidence": round(ind.confidence, 4),
                    "matched_keywords": ind.matched_keywords,
                    "matched_patterns": ind.matched_patterns,
                }
                for ind in self.indicators
            ],
            "error": self.error,
        }
