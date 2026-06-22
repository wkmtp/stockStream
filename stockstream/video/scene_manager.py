"""Smart Scene Engine — automatically matches background content to spoken commentary.

Analyzes TTS sentence text in real time and switches the display scene to the
most relevant chart/indicator/analysis view.

Scene types (10 total):
    1. K线图      — K-line candlestick chart with MA overlays
    2. 分时图      — Intraday price trend line
    3. 成交量      — Volume bar chart (standalone, enlarged)
    4. MACD       — MACD indicator (DIF/DEA/histogram)
    5. RSI        — RSI indicator (overbought/oversold zones)
    6. 主力资金流向 — Main capital flow bars
    7. 龙虎榜      — Top trader rankings (dragon-tiger board)
    8. 板块热力图   — Sector heatmap
    9. 涨跌家数统计 — Advance/decline statistics
    10. AI分析摘要  — AI-generated analysis summary card

Layout: digital human on the LEFT 25%, dynamic scene on the RIGHT 75%.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Optional

import numpy as np

from stockstream.video.chart_renderer import StockChartRenderer

logger = logging.getLogger(__name__)


# ── scene type enumeration ────────────────────────────────────────────────

class SceneType(str, Enum):
    """All supported background scene types for the livestream."""

    KLINE = "kline"                    # K线图（含成交量+均线）
    MINUTE = "minute"                  # 分时图
    VOLUME = "volume"                  # 成交量（独立放大）
    MACD = "macd"                      # MACD 指标
    RSI = "rsi"                        # RSI 指标
    FUND_FLOW = "fund_flow"            # 主力资金流向
    DRAGON_TIGER = "dragon_tiger"      # 龙虎榜
    SECTOR_HEATMAP = "sector_heatmap"  # 板块热力图
    ADVANCE_DECLINE = "advance_decline"  # 涨跌家数统计
    AI_SUMMARY = "ai_summary"          # AI分析摘要
    SLIDE_OPEN = "slide_open"          # AI选股幻灯片 - 建仓推荐
    SLIDE_ADD = "slide_add"            # AI选股幻灯片 - 补仓推荐
    SLIDE_REDUCE = "slide_reduce"      # AI选股幻灯片 - 减仓提示
    SLIDE_CLEAR = "slide_clear"        # AI选股幻灯片 - 清仓提示
    SLIDE_RISK = "slide_risk"          # AI选股幻灯片 - 风险提示
    DASHBOARD = "dashboard"            # 全屏财经数据大屏

    @property
    def label(self) -> str:
        _labels = {
            SceneType.KLINE: "K线图",
            SceneType.MINUTE: "分时图",
            SceneType.VOLUME: "成交量",
            SceneType.MACD: "MACD",
            SceneType.RSI: "RSI",
            SceneType.FUND_FLOW: "主力资金流向",
            SceneType.DRAGON_TIGER: "龙虎榜",
            SceneType.SECTOR_HEATMAP: "板块热力图",
            SceneType.ADVANCE_DECLINE: "涨跌家数统计",
            SceneType.AI_SUMMARY: "AI分析摘要",
            SceneType.SLIDE_OPEN: "建仓推荐",
            SceneType.SLIDE_ADD: "补仓推荐",
            SceneType.SLIDE_REDUCE: "减仓提示",
            SceneType.SLIDE_CLEAR: "清仓提示",
            SceneType.SLIDE_RISK: "风险提示",
            SceneType.DASHBOARD: "财经数据大屏",
        }
        return _labels.get(self, self.value)


# ── scene data container ──────────────────────────────────────────────────

@dataclass
class SceneData:
    """Data required to render the current scene."""

    scene_type: SceneType = SceneType.KLINE

    # Stock info
    symbol: str = ""
    name: str = ""
    price_now: float = 0.0
    change_pct: float = 0.0

    # K-line / daily data
    kline_data: list[dict] = field(default_factory=list)

    # Minute data
    minute_data: list[dict] = field(default_factory=list)

    # Fund flow data
    fund_data: list[dict] = field(default_factory=list)

    # Dragon-tiger board data
    dragon_tiger_data: list[dict] = field(default_factory=list)

    # Sector heatmap data
    sector_data: list[dict] = field(default_factory=list)

    # Advance/decline statistics
    advance_decline_data: dict = field(default_factory=dict)

    # AI summary text
    ai_summary_text: str = ""

    # Computed indicator values (populated from kline_data)
    macd_dif: list[float] = field(default_factory=list)
    macd_dea: list[float] = field(default_factory=list)
    macd_histogram: list[float] = field(default_factory=list)
    rsi_values: list[float] = field(default_factory=list)

    # Subtitle sync
    subtitle_text: str = ""
    speaker_label: str = "AI主播"

    def has_kline(self) -> bool:
        return len(self.kline_data) >= 5

    def has_minute(self) -> bool:
        return len(self.minute_data) >= 5

    def has_fund(self) -> bool:
        return len(self.fund_data) >= 1

    def has_dragon_tiger(self) -> bool:
        return len(self.dragon_tiger_data) >= 1

    def has_sector(self) -> bool:
        return len(self.sector_data) >= 1

    def has_advance_decline(self) -> bool:
        return bool(self.advance_decline_data)

    def has_ai_summary(self) -> bool:
        return bool(self.ai_summary_text)


# ── keyword → scene matching rules ────────────────────────────────────────

@dataclass
class _KeywordRule:
    """A keyword matching rule with priority and regex patterns."""

    scene: SceneType
    keywords: list[str]          # Chinese keyword phrases
    patterns: list[str]          # Regex patterns (compiled lazily)
    priority: int = 0            # Higher = preferred when multiple match
    min_confidence: float = 0.6  # Min confidence to trigger this scene


# ── keyword rule table ────────────────────────────────────────────────────

_SCENE_RULES: list[_KeywordRule] = [
    # MACD — highest priority for specific technical signals
    _KeywordRule(
        scene=SceneType.MACD,
        keywords=["MACD", "金叉", "死叉", "金叉买入", "死叉卖出", "dif", "dea",
                   "底背离", "顶背离", "macd金叉", "macd死叉",
                   "MACD金叉", "MACD死叉", "柱状线", "macd柱"],
        patterns=[r"(?i)\bmacd\b", r"金叉|死叉"],
        priority=100,
        min_confidence=0.55,
    ),

    # RSI — overbought/oversold
    _KeywordRule(
        scene=SceneType.RSI,
        keywords=["RSI", "rsi", "超买", "超卖", "相对强弱", "RSI指标",
                   "rsi超买", "rsi超卖", "RSI超买", "RSI超卖"],
        patterns=[r"(?i)\brsi\b", r"超买|超卖"],
        priority=90,
        min_confidence=0.55,
    ),

    # Fund flow — capital movement
    _KeywordRule(
        scene=SceneType.FUND_FLOW,
        keywords=["主力资金", "资金流向", "净流入", "净流出", "主力净流入", "主力净流出",
                   "超大单", "大单净", "中单净", "小单净", "北向资金", "北向流入",
                   "北向流出", "资金净", "主力进场", "主力出逃", "主力加仓", "主力减仓",
                   "资金面", "大资金", "机构资金", "游资"],
        patterns=[r"主力.*(?:流入|流出|进场|出逃|加仓|减仓|资金)",
                   r"(?:北向|外资|机构|游资).*(?:流入|流出|买入|卖出)",
                   r"资金.*(?:净流入|净流出|流入|流出)"],
        priority=85,
        min_confidence=0.5,
    ),

    # Dragon-tiger board
    _KeywordRule(
        scene=SceneType.DRAGON_TIGER,
        keywords=["龙虎榜", "龙虎", "上榜", "营业部", "席位", "游资席位",
                   "龙虎榜净买入", "龙虎榜净卖出", "机构专用", "知名游资"],
        patterns=[r"龙虎榜|龙虎", r"营业部|席位", r"(?:机构|游资).*(?:专用|买入|卖出)"],
        priority=80,
        min_confidence=0.55,
    ),

    # Sector heatmap
    _KeywordRule(
        scene=SceneType.SECTOR_HEATMAP,
        keywords=["板块", "行业", "概念", "板块轮动", "板块表现", "板块涨幅",
                   "板块跌幅", "领涨板块", "领跌板块", "热点板块", "热力图",
                   "板块活跃", "白酒板块", "新能源板块", "半导体板块", "AI板块",
                   "芯片板块", "医药板块", "消费板块", "金融板块", "地产板块",
                   "军工板块", "光伏板块", "汽车板块", "煤炭板块", "有色板块"],
        patterns=[r"(?:白酒|新能源|半导体|AI|芯片|医药|消费|金融|地产|军工|光伏|汽车|煤炭|有色)\s*板块",
                   r"板块.*(?:表现|涨幅|跌幅|轮动|活跃|拉升|走强|走弱)",
                   r"(?:领涨|领跌|热点).*板块"],
        priority=75,
        min_confidence=0.5,
    ),

    # Volume
    _KeywordRule(
        scene=SceneType.VOLUME,
        keywords=["成交量", "成交额", "放量", "缩量", "地量", "天量",
                   "量能", "换手率", "换手", "放量上涨", "缩量下跌",
                   "量价齐升", "量价背离", "成交活跃", "成交低迷"],
        patterns=[r"(?:成交|量能|换手)", r"放量|缩量|地量|天量"],
        priority=70,
        min_confidence=0.5,
    ),

    # Minute chart
    _KeywordRule(
        scene=SceneType.MINUTE,
        keywords=["分时", "盘中", "日内", "开盘", "午盘", "尾盘", "收盘",
                   "盘中拉升", "尾盘跳水", "早盘", "盘中异动", "盘中走势",
                   "分时图", "日内波动", "盘中震荡"],
        patterns=[r"分时|盘中|日内|开盘|午盘|尾盘|早盘"],
        priority=65,
        min_confidence=0.5,
    ),

    # Advance/decline
    _KeywordRule(
        scene=SceneType.ADVANCE_DECLINE,
        keywords=["涨跌家数", "涨跌比", "涨多跌少", "跌多涨少", "普涨", "普跌",
                   "上涨家数", "下跌家数", "涨停家数", "跌停家数",
                   "市场情绪", "赚钱效应", "市场热度", "个股涨跌"],
        patterns=[r"涨跌.*(?:家数|比)", r"(?:上涨|下跌|涨停|跌停).*家数",
                   r"(?:普涨|普跌)", r"赚钱效应"],
        priority=60,
        min_confidence=0.5,
    ),

    # AI slide - 建仓推荐
    _KeywordRule(
        scene=SceneType.SLIDE_OPEN,
        keywords=["建仓", "买入推荐", "建仓推荐", "选股结果", "建仓标的",
                   "开仓", "进场", "买入信号", "入池", "入选", "推荐标的"],
        patterns=[r"建仓.*(?:推荐|标的|信号)", r"(?:买入|进场|开仓).*(?:推荐|信号)"],
        priority=95,
        min_confidence=0.55,
    ),

    # AI slide - 补仓推荐
    _KeywordRule(
        scene=SceneType.SLIDE_ADD,
        keywords=["补仓", "加仓", "补仓推荐", "加仓信号", "补仓标的",
                   "增持", "追加", "摊薄成本"],
        patterns=[r"(?:补仓|加仓|增持).*(?:推荐|信号|标的)"],
        priority=92,
        min_confidence=0.55,
    ),

    # AI slide - 风险提示
    _KeywordRule(
        scene=SceneType.SLIDE_RISK,
        keywords=["风险提示", "风险警示", "风险控制", "止损", "风控",
                   "仓位管理", "风险敞口", "回撤控制"],
        patterns=[r"风险.*(?:提示|警示|控制|管理)", r"止损|风控"],
        priority=88,
        min_confidence=0.55,
    ),

    # Dashboard — 财经数据大屏 (highest priority)
    _KeywordRule(
        scene=SceneType.DASHBOARD,
        keywords=["数据大屏", "财经大屏", "大盘概览", "市场总览", "全市场",
                   "三大指数", "上证指数", "深证成指", "创业板指", "北向资金",
                   "涨跌家数", "热点板块", "资金流向", "涨停家数", "跌停家数",
                   "市场数据", "盘面数据", "指数概览"],
        patterns=[r"(?:大盘|市场|盘面|指数).*(?:概览|总览|数据|大屏|一览)"],
        priority=98,
        min_confidence=0.55,
    ),

    # AI summary
    _KeywordRule(
        scene=SceneType.AI_SUMMARY,
        keywords=["分析", "总结", "观点", "建议", "策略", "预判", "展望",
                   "AI分析", "AI总结", "智能分析", "综合研判", "后市",
                   "投资建议", "操作建议", "估值", "基本面"],
        patterns=[r"(?:AI|智能).*(?:分析|总结|研判)", r"(?:后市|展望|预判)"],
        priority=50,
        min_confidence=0.5,
    ),

    # K-line — default fallback (lowest priority)
    _KeywordRule(
        scene=SceneType.KLINE,
        keywords=["K线", "走势", "行情", "趋势", "均线", "突破", "回踩",
                   "支撑", "压力", "上涨", "下跌", "涨停", "跌停", "反弹",
                   "回调", "新高", "新低", "多头", "空头", "阳线", "阴线",
                   "MA5", "MA10", "MA20", "MA60", "布林带", "BOLL"],
        patterns=[r"K线|走势|行情|趋势|均线|突破|回踩|支撑|压力"],
        priority=10,
        min_confidence=0.3,
    ),
]


# ── scene manager ─────────────────────────────────────────────────────────

class SceneManager:
    """Analyze TTS sentence text and determine the most relevant display scene.

    Usage::

        mgr = SceneManager()
        mgr.update_market_data(symbol="600519", kline_data=rows, ...)

        # Called from TTS on_sentence callback:
        scene = mgr.match_scene("贵州茅台今日MACD金叉，主力资金净流入2.1亿")
        if scene != mgr.current_scene:
            mgr.switch_to(scene)

        # Get the rendered scene image for compositing:
        scene_rgba = mgr.render_current_scene()
    """

    def __init__(
        self,
        default_scene: SceneType = SceneType.KLINE,
        cooldown_sec: float = 3.0,
        min_switch_interval: float = 1.5,
    ) -> None:
        self._data = SceneData(scene_type=default_scene)
        self._current_scene = default_scene
        self._default_scene = default_scene
        self._cooldown_sec = cooldown_sec
        self._min_switch_interval = min_switch_interval
        self._last_switch_time: float = 0.0
        self._scene_timers: dict[SceneType, float] = {}
        self._chart_renderer: Optional[StockChartRenderer] = None
        self._cached_scene_rgba: Optional[np.ndarray] = None
        self._scene_dirty: bool = True

        # Compile regex patterns
        for rule in _SCENE_RULES:
            rule._compiled = [re.compile(p) for p in rule.patterns]

    # ── properties ───────────────────────────────────────────────────

    @property
    def current_scene(self) -> SceneType:
        return self._current_scene

    @property
    def scene_data(self) -> SceneData:
        return self._data

    @property
    def scene_label(self) -> str:
        return self._current_scene.label

    # ── market data update ───────────────────────────────────────────

    def update_market_data(
        self,
        symbol: str = "",
        name: str = "",
        price: float = 0.0,
        change_pct: float = 0.0,
        kline_data: list[dict] | None = None,
        minute_data: list[dict] | None = None,
        fund_data: list[dict] | None = None,
        dragon_tiger_data: list[dict] | None = None,
        sector_data: list[dict] | None = None,
        advance_decline_data: dict | None = None,
        ai_summary_text: str = "",
    ) -> None:
        """Update cached market data for scene rendering."""
        d = self._data
        if symbol:
            d.symbol = symbol
        if name:
            d.name = name
        d.price_now = price
        d.change_pct = change_pct
        if kline_data is not None:
            d.kline_data = kline_data
            self._compute_indicators(kline_data)
        if minute_data is not None:
            d.minute_data = minute_data
        if fund_data is not None:
            d.fund_data = fund_data
        if dragon_tiger_data is not None:
            d.dragon_tiger_data = dragon_tiger_data
        if sector_data is not None:
            d.sector_data = sector_data
        if advance_decline_data is not None:
            d.advance_decline_data = advance_decline_data
        if ai_summary_text:
            d.ai_summary_text = ai_summary_text

        self._scene_dirty = True

    def update_subtitle(self, text: str, speaker: str = "AI主播") -> None:
        """Update the subtitle text for scene-aware display."""
        self._data.subtitle_text = text
        self._data.speaker_label = speaker

    # ── scene matching ───────────────────────────────────────────────

    def match_scene(self, text: str) -> SceneType:
        """Analyze text and return the best-matching scene type.

        Args:
            text: The TTS sentence text to analyze.

        Returns:
            The best matching SceneType. Falls back to KLINE if nothing matches.
        """
        if not text or not text.strip():
            return self._default_scene

        text_lower = text.lower().strip()
        candidates: list[tuple[SceneType, float, int]] = []

        for rule in _SCENE_RULES:
            score = self._score_rule(rule, text, text_lower)
            if score >= rule.min_confidence:
                candidates.append((rule.scene, score, rule.priority))

        if not candidates:
            return self._default_scene

        # Sort by: priority desc, then score desc
        candidates.sort(key=lambda x: (x[2], x[1]), reverse=True)
        best_scene = candidates[0][0]

        # Validate that we have data for this scene
        if not self._has_data_for_scene(best_scene):
            # Try next best candidate with available data
            for scene, score, pri in candidates[1:]:
                if self._has_data_for_scene(scene):
                    return scene
            return self._default_scene

        logger.debug("Matched scene '%s' for text: %s", best_scene.label, text[:60])
        return best_scene

    def should_switch(self, new_scene: SceneType) -> bool:
        """Check if we should switch to *new_scene* considering cooldown."""
        now = time.monotonic()

        # Same scene — no switch needed
        if new_scene == self._current_scene:
            return False

        # Minimum switch interval
        if now - self._last_switch_time < self._min_switch_interval:
            return False

        # Scene cooldown: don't switch back to a recently shown scene
        last_shown = self._scene_timers.get(new_scene, 0)
        if now - last_shown < self._cooldown_sec:
            return False

        # Check data availability
        if not self._has_data_for_scene(new_scene):
            return False

        return True

    def switch_to(self, scene: SceneType) -> bool:
        """Switch to the given scene. Returns True if actually switched."""
        if not self.should_switch(scene):
            return False

        old = self._current_scene
        now = time.monotonic()

        self._scene_timers[old] = now
        self._current_scene = scene
        self._data.scene_type = scene
        self._last_switch_time = now
        self._scene_dirty = True

        logger.info("Scene switch: %s → %s", old.label, scene.label)
        return True

    def force_switch(self, scene: SceneType) -> None:
        """Force switch to a scene, bypassing cooldown and data checks."""
        old = self._current_scene
        self._current_scene = scene
        self._data.scene_type = scene
        self._last_switch_time = time.monotonic()
        self._scene_timers[old] = time.monotonic()
        self._scene_dirty = True
        logger.info("Scene forced: %s → %s", old.label, scene.label)

    def process_sentence(self, text: str) -> Optional[SceneType]:
        """Full pipeline: match + switch. Returns new scene if switched, else None."""
        scene = self.match_scene(text)
        if self.switch_to(scene):
            return scene
        return None

    # ── scene rendering ──────────────────────────────────────────────

    def render_current_scene(
        self,
        width_px: int = 1440,
        height_px: int = 880,
        force_refresh: bool = False,
    ) -> np.ndarray:
        """Render the current scene as an RGBA numpy array.

        Args:
            width_px: Output width in pixels.
            height_px: Output height in pixels.
            force_refresh: If True, re-render even if cached.

        Returns:
            numpy uint8 RGBA array (height_px, width_px, 4).
        """
        if not self._scene_dirty and not force_refresh and self._cached_scene_rgba is not None:
            return self._cached_scene_rgba

        scene = self._current_scene
        renderer = self._get_renderer(width_px, height_px)
        data = self._data

        try:
            if scene == SceneType.KLINE:
                rgba = renderer.render_kline(
                    symbol=data.symbol, name=data.name,
                    kline_data=data.kline_data,
                    fund_data=data.fund_data,
                    price_now=data.price_now,
                    change_pct=data.change_pct,
                )
            elif scene == SceneType.MINUTE:
                rgba = renderer.render_price_line(
                    symbol=data.symbol, name=data.name,
                    data=data.minute_data if data.has_minute() else data.kline_data,
                    price_now=data.price_now,
                    change_pct=data.change_pct,
                )
            elif scene == SceneType.VOLUME:
                rgba = self._render_volume_scene(renderer, data, width_px, height_px)
            elif scene == SceneType.MACD:
                rgba = self._render_macd_scene(renderer, data, width_px, height_px)
            elif scene == SceneType.RSI:
                rgba = self._render_rsi_scene(renderer, data, width_px, height_px)
            elif scene == SceneType.FUND_FLOW:
                rgba = renderer.render_kline(
                    symbol=data.symbol, name=data.name,
                    kline_data=data.kline_data,
                    fund_data=data.fund_data,
                    price_now=data.price_now,
                    change_pct=data.change_pct,
                )
            elif scene == SceneType.DRAGON_TIGER:
                rgba = self._render_dragon_tiger_scene(renderer, data, width_px, height_px)
            elif scene == SceneType.SECTOR_HEATMAP:
                rgba = self._render_sector_heatmap_scene(renderer, data, width_px, height_px)
            elif scene == SceneType.ADVANCE_DECLINE:
                rgba = self._render_advance_decline_scene(renderer, data, width_px, height_px)
            elif scene == SceneType.AI_SUMMARY:
                rgba = self._render_ai_summary_scene(renderer, data, width_px, height_px)
            elif scene in (SceneType.SLIDE_OPEN, SceneType.SLIDE_ADD,
                           SceneType.SLIDE_REDUCE, SceneType.SLIDE_CLEAR,
                           SceneType.SLIDE_RISK):
                rgba = self._render_slide_scene(scene, width_px, height_px)
            elif scene == SceneType.DASHBOARD:
                rgba = self._render_dashboard_scene(width_px, height_px)
            else:
                rgba = renderer.render_kline(
                    symbol=data.symbol, name=data.name,
                    kline_data=data.kline_data,
                    fund_data=data.fund_data,
                    price_now=data.price_now,
                    change_pct=data.change_pct,
                )

            self._cached_scene_rgba = rgba
            self._scene_dirty = False
            return rgba

        except Exception as exc:
            logger.exception("Failed to render scene %s: %s", scene.label, exc)
            # Fallback: return a dark placeholder
            placeholder = np.zeros((height_px, width_px, 4), dtype=np.uint8)
            placeholder[:, :, :3] = (13, 17, 23)
            placeholder[:, :, 3] = 255
            return placeholder

    # ── scene-specific renderers ─────────────────────────────────────

    def _render_volume_scene(
        self, renderer: StockChartRenderer, data: SceneData,
        width_px: int, height_px: int,
    ) -> np.ndarray:
        """Render a standalone volume chart (enlarged)."""
        # Use kline renderer but emphasize volume section — reuse K-line which includes volume
        rgba = renderer.render_kline(
            symbol=data.symbol, name=data.name,
            kline_data=data.kline_data,
            fund_data=data.fund_data,
            price_now=data.price_now,
            change_pct=data.change_pct,
        )
        return rgba

    def _render_macd_scene(
        self, renderer: StockChartRenderer, data: SceneData,
        width_px: int, height_px: int,
    ) -> np.ndarray:
        """Render a MACD indicator chart."""
        return self._render_indicator_chart(
            renderer, data, width_px, height_px,
            indicator_type="MACD",
            title=f"{data.name}({data.symbol}) MACD",
        )

    def _render_rsi_scene(
        self, renderer: StockChartRenderer, data: SceneData,
        width_px: int, height_px: int,
    ) -> np.ndarray:
        """Render an RSI indicator chart."""
        return self._render_indicator_chart(
            renderer, data, width_px, height_px,
            indicator_type="RSI",
            title=f"{data.name}({data.symbol}) RSI",
        )

    def _render_indicator_chart(
        self, renderer: StockChartRenderer, data: SceneData,
        width_px: int, height_px: int,
        indicator_type: str, title: str,
    ) -> np.ndarray:
        """Generic indicator chart renderer using matplotlib."""
        import io
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.font_manager import FontProperties

        dpi = 100
        w_in = width_px / dpi
        h_in = height_px / dpi

        fig = plt.figure(figsize=(w_in, h_in), dpi=dpi,
                         facecolor=renderer.facecolor)

        if indicator_type == "MACD":
            ax = fig.add_subplot(111, facecolor=renderer.facecolor)
            self._draw_macd(ax, data, renderer)
        elif indicator_type == "RSI":
            ax = fig.add_subplot(111, facecolor=renderer.facecolor)
            self._draw_rsi(ax, data, renderer)
        else:
            plt.close(fig)
            return np.zeros((height_px, width_px, 4), dtype=np.uint8)

        # Title
        from stockstream.video.chart_renderer import ChartColors as _cc
        font = renderer._font if hasattr(renderer, '_font') else FontProperties()
        color = _cc.GREEN if data.change_pct >= 0 else _cc.RED
        ax.set_title(title, color=color, fontproperties=font, fontsize=16, pad=10, loc="left")

        buf = io.BytesIO()
        fig.savefig(buf, format="rgba", dpi=dpi, facecolor=renderer.facecolor,
                    edgecolor="none", pad_inches=0)
        plt.close(fig)

        buf.seek(0)
        rgba = np.frombuffer(buf.getvalue(), dtype=np.uint8)
        rgba = rgba.reshape(height_px, width_px, 4)
        return rgba

    def _draw_macd(self, ax, data: SceneData, renderer: StockChartRenderer) -> None:
        """Draw MACD DIF/DEA/histogram on the given axes."""
        import matplotlib.pyplot as plt
        from stockstream.video.chart_renderer import ChartColors as cc

        if data.macd_dif and data.macd_dea and data.macd_histogram:
            xs = list(range(len(data.macd_dif)))
            ax.plot(xs, data.macd_dif, color=cc.BLUE, linewidth=1.2, label="DIF")
            ax.plot(xs, data.macd_dea, color=cc.ORANGE, linewidth=1.2, label="DEA")

            # Histogram bars
            for i, (x, val) in enumerate(zip(xs, data.macd_histogram)):
                color = cc.GREEN if val >= 0 else cc.RED
                ax.bar(x, val, width=0.6, color=color, alpha=0.7)

            ax.axhline(y=0, color=cc.TEXT_DIM, linewidth=0.5, linestyle="-")

        ax.set_facecolor(renderer.facecolor)
        ax.tick_params(colors=cc.TEXT_DIM, labelsize=9)
        for spine in ax.spines.values():
            spine.set_color(cc.GRID)
        ax.grid(True, color=cc.GRID, alpha=0.4, linestyle=":", linewidth=0.5)
        ax.legend(loc="upper left", fontsize=9, facecolor=renderer.facecolor,
                  edgecolor=cc.GRID, labelcolor=cc.TEXT)

    def _draw_rsi(self, ax, data: SceneData, renderer: StockChartRenderer) -> None:
        """Draw RSI line with overbought/oversold zones."""
        import matplotlib.pyplot as plt
        from stockstream.video.chart_renderer import ChartColors as cc

        if data.rsi_values:
            xs = list(range(len(data.rsi_values)))
            ax.plot(xs, data.rsi_values, color=cc.PURPLE, linewidth=1.5, label="RSI(14)")

        # Overbought / oversold reference lines
        ax.axhline(y=70, color=cc.RED, linewidth=1.0, linestyle="--", alpha=0.6, label="超买 70")
        ax.axhline(y=30, color=cc.GREEN, linewidth=1.0, linestyle="--", alpha=0.6, label="超卖 30")
        ax.axhline(y=50, color=cc.TEXT_DIM, linewidth=0.5, linestyle=":", alpha=0.4)
        ax.set_ylim(0, 100)

        # Shade zones
        ax.axhspan(70, 100, alpha=0.08, color=cc.RED)
        ax.axhspan(0, 30, alpha=0.08, color=cc.GREEN)

        ax.set_facecolor(renderer.facecolor)
        ax.tick_params(colors=cc.TEXT_DIM, labelsize=9)
        for spine in ax.spines.values():
            spine.set_color(cc.GRID)
        ax.grid(True, color=cc.GRID, alpha=0.4, linestyle=":", linewidth=0.5)
        ax.legend(loc="upper left", fontsize=9, facecolor=renderer.facecolor,
                  edgecolor=cc.GRID, labelcolor=cc.TEXT)

    def _render_dragon_tiger_scene(
        self, renderer: StockChartRenderer, data: SceneData,
        width_px: int, height_px: int,
    ) -> np.ndarray:
        """Render dragon-tiger board rankings."""
        import io
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.font_manager import FontProperties

        from stockstream.video.chart_renderer import ChartColors as cc

        dpi = 100
        w_in = width_px / dpi
        h_in = height_px / dpi
        font = renderer._font if hasattr(renderer, '_font') else FontProperties()

        fig = plt.figure(figsize=(w_in, h_in), dpi=dpi,
                         facecolor=renderer.facecolor)
        ax = fig.add_subplot(111, facecolor=renderer.facecolor)

        if data.has_dragon_tiger():
            # Build table
            rows = data.dragon_tiger_data[:15]
            col_labels = ["排名", "营业部", "买入(亿)", "卖出(亿)", "净额(亿)"]
            table_data = []
            for i, row in enumerate(rows):
                p = row.get("payload", row)
                table_data.append([
                    str(i + 1),
                    str(p.get("营业部", p.get("name", "")))[:12],
                    f"{float(p.get('买入额', p.get('buy', 0))) / 1e8:.2f}",
                    f"{float(p.get('卖出额', p.get('sell', 0))) / 1e8:.2f}",
                    f"{float(p.get('净买入额', p.get('net', 0))) / 1e8:+.2f}",
                ])

            ax.axis("off")
            table = ax.table(
                cellText=table_data,
                colLabels=col_labels,
                cellLoc="center",
                loc="center",
            )
            table.auto_set_font_size(False)
            table.set_fontsize(11)
            table.scale(1.0, 1.8)
            # Style the table
            for key, cell in table.get_celld().items():
                cell.set_edgecolor(cc.GRID)
                if key[0] == 0:  # header
                    cell.set_facecolor("#1a1a2e")
                    cell.set_text_props(color=cc.WHITE, fontproperties=font)
                else:
                    cell.set_facecolor(renderer.facecolor)
                    cell.set_text_props(color=cc.TEXT, fontproperties=font)
        else:
            ax.text(0.5, 0.5, "等待龙虎榜数据...", transform=ax.transAxes,
                    ha="center", va="center", fontsize=18, fontproperties=font,
                    color=cc.TEXT_DIM)
            ax.axis("off")

        ax.set_title(f"龙虎榜 — {data.name or '全市场'}", fontsize=16,
                     fontproperties=font, color=cc.WHITE, pad=10, loc="left")

        buf = io.BytesIO()
        fig.savefig(buf, format="rgba", dpi=dpi, facecolor=renderer.facecolor,
                    edgecolor="none", pad_inches=0)
        plt.close(fig)
        buf.seek(0)
        rgba = np.frombuffer(buf.getvalue(), dtype=np.uint8)
        rgba = rgba.reshape(height_px, width_px, 4)
        return rgba

    def _render_sector_heatmap_scene(
        self, renderer: StockChartRenderer, data: SceneData,
        width_px: int, height_px: int,
    ) -> np.ndarray:
        """Render sector heatmap as horizontal bar chart."""
        import io
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.font_manager import FontProperties

        from stockstream.video.chart_renderer import ChartColors as cc

        dpi = 100
        w_in = width_px / dpi
        h_in = height_px / dpi
        font = renderer._font if hasattr(renderer, '_font') else FontProperties()

        fig = plt.figure(figsize=(w_in, h_in), dpi=dpi,
                         facecolor=renderer.facecolor)
        ax = fig.add_subplot(111, facecolor=renderer.facecolor)

        if data.has_sector():
            sectors = data.sector_data[:20]
            names = []
            values = []
            for s in sectors:
                p = s.get("payload", s)
                names.append(str(p.get("板块", p.get("name", "")))[:10])
                try:
                    values.append(float(p.get("涨跌幅", p.get("change", 0))))
                except (ValueError, TypeError):
                    values.append(0.0)

            # Sort by absolute value for visual impact
            paired = sorted(zip(names, values), key=lambda x: abs(x[1]), reverse=True)
            names = [p[0] for p in paired]
            values = [p[1] for p in paired]

            y_pos = range(len(names))
            colors = [cc.GREEN if v >= 0 else cc.RED for v in values]
            bars = ax.barh(y_pos, values, color=colors, height=0.7, alpha=0.85)

            ax.set_yticks(y_pos)
            ax.set_yticklabels(names, fontproperties=font, fontsize=10, color=cc.TEXT)
            ax.invert_yaxis()

            for bar, val in zip(bars, values):
                label = f"{val:+.2f}%"
                x_pos = bar.get_width()
                ha = "left" if val >= 0 else "right"
                offset = 0.1 if val >= 0 else -0.1
                ax.text(x_pos + offset, bar.get_y() + bar.get_height() / 2,
                        label, va="center", ha=ha, fontsize=9,
                        color=cc.TEXT, fontproperties=font)

        else:
            ax.text(0.5, 0.5, "等待板块数据...", transform=ax.transAxes,
                    ha="center", va="center", fontsize=18, fontproperties=font,
                    color=cc.TEXT_DIM)
            ax.axis("off")

        ax.set_facecolor(renderer.facecolor)
        ax.tick_params(colors=cc.TEXT_DIM, labelsize=10)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.axvline(x=0, color=cc.TEXT_DIM, linewidth=0.8, alpha=0.5)

        ax.set_title(f"板块热力图 — {data.name or '全市场'}", fontsize=16,
                     fontproperties=font, color=cc.WHITE, pad=10, loc="left")

        buf = io.BytesIO()
        fig.savefig(buf, format="rgba", dpi=dpi, facecolor=renderer.facecolor,
                    edgecolor="none", pad_inches=0)
        plt.close(fig)
        buf.seek(0)
        rgba = np.frombuffer(buf.getvalue(), dtype=np.uint8)
        rgba = rgba.reshape(height_px, width_px, 4)
        return rgba

    def _render_advance_decline_scene(
        self, renderer: StockChartRenderer, data: SceneData,
        width_px: int, height_px: int,
    ) -> np.ndarray:
        """Render advance/decline statistics chart."""
        import io
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.font_manager import FontProperties

        from stockstream.video.chart_renderer import ChartColors as cc

        dpi = 100
        w_in = width_px / dpi
        h_in = height_px / dpi
        font = renderer._font if hasattr(renderer, '_font') else FontProperties()

        fig = plt.figure(figsize=(w_in, h_in), dpi=dpi,
                         facecolor=renderer.facecolor)

        if data.has_advance_decline():
            ad = data.advance_decline_data
            up_count = int(ad.get("上涨家数", ad.get("up", 0)))
            down_count = int(ad.get("下跌家数", ad.get("down", 0)))
            flat_count = int(ad.get("平盘家数", ad.get("flat", 0)))
            limit_up = int(ad.get("涨停家数", ad.get("limit_up", 0)))
            limit_down = int(ad.get("跌停家数", ad.get("limit_down", 0)))

            # Pie chart for up/down/flat
            ax1 = fig.add_subplot(121, facecolor=renderer.facecolor)
            sizes = [up_count, down_count, flat_count]
            labels = [f"上涨 {up_count}", f"下跌 {down_count}", f"平盘 {flat_count}"]
            colors_pie = [cc.GREEN, cc.RED, cc.TEXT_DIM]
            ax1.pie(sizes, labels=labels, colors=colors_pie, autopct="%1.1f%%",
                    textprops={"fontproperties": font, "fontsize": 11, "color": cc.WHITE})
            ax1.set_title("涨跌分布", fontproperties=font, fontsize=14, color=cc.WHITE, pad=10)

            # Bar chart for limit up/down
            ax2 = fig.add_subplot(122, facecolor=renderer.facecolor)
            bars = ax2.bar(["涨停", "跌停"], [limit_up, limit_down],
                           color=[cc.GREEN, cc.RED], width=0.4, alpha=0.85)
            for bar, val in zip(bars, [limit_up, limit_down]):
                ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                         str(val), ha="center", va="bottom", fontsize=14,
                         color=cc.WHITE, fontproperties=font)
            ax2.set_title("涨跌停家数", fontproperties=font, fontsize=14, color=cc.WHITE, pad=10)
            ax2.set_facecolor(renderer.facecolor)
            ax2.tick_params(colors=cc.TEXT_DIM, labelsize=10)
            for spine in ax2.spines.values():
                spine.set_color(cc.GRID)
        else:
            ax = fig.add_subplot(111, facecolor=renderer.facecolor)
            ax.text(0.5, 0.5, "等待涨跌家数数据...", transform=ax.transAxes,
                    ha="center", va="center", fontsize=18, fontproperties=font,
                    color=cc.TEXT_DIM)
            ax.axis("off")

        fig.suptitle(f"涨跌家数统计 — {data.name or '全市场'}",
                     fontproperties=font, fontsize=16, color=cc.WHITE, y=0.98)

        buf = io.BytesIO()
        fig.savefig(buf, format="rgba", dpi=dpi, facecolor=renderer.facecolor,
                    edgecolor="none", pad_inches=0)
        plt.close(fig)
        buf.seek(0)
        rgba = np.frombuffer(buf.getvalue(), dtype=np.uint8)
        rgba = rgba.reshape(height_px, width_px, 4)
        return rgba

    def _render_ai_summary_scene(
        self, renderer: StockChartRenderer, data: SceneData,
        width_px: int, height_px: int,
    ) -> np.ndarray:
        """Render AI analysis summary as a styled text card."""
        from PIL import Image, ImageDraw, ImageFont

        from stockstream.video.chart_renderer import ChartColors as cc
        from stockstream.video.subtitle_renderer import FONT_PATH

        # Create card
        img = Image.new("RGBA", (width_px, height_px),
                        tuple(int(cc.BG.lstrip("#")[i:i+2], 16) for i in (0, 2, 4)) + (255,))
        draw = ImageDraw.Draw(img)

        # Try to load font
        try:
            if FONT_PATH:
                title_font = ImageFont.truetype(FONT_PATH, 28)
                body_font = ImageFont.truetype(FONT_PATH, 20)
                small_font = ImageFont.truetype(FONT_PATH, 16)
            else:
                title_font = ImageFont.load_default()
                body_font = ImageFont.load_default()
                small_font = ImageFont.load_default()
        except Exception:
            title_font = ImageFont.load_default()
            body_font = ImageFont.load_default()
            small_font = ImageFont.load_default()

        # Title
        title = "AI 智能分析摘要"
        draw.text((40, 30), title, font=title_font, fill=(88, 166, 255, 255))

        # Decorative line
        draw.line([(40, 75), (width_px - 40, 75)], fill=(88, 166, 255, 100), width=2)

        # Stock info box
        info_text = f"{data.name} ({data.symbol})  |  {data.price_now:.2f}  |  {data.change_pct:+.2f}%"
        info_color = (63, 185, 80, 255) if data.change_pct >= 0 else (248, 81, 73, 255)
        draw.text((40, 95), info_text, font=body_font, fill=info_color)

        # Summary text — wrapped
        summary = data.ai_summary_text or "等待 AI 分析结果..."
        lines = _wrap_text_pil(summary, width_px - 80, body_font, draw)

        y = 140
        for line in lines[:12]:  # max 12 lines
            draw.text((40, y), line, font=body_font, fill=(201, 209, 217, 255))
            y += 40

        # Footer
        draw.text((40, height_px - 50), "以上分析由 AI 生成，仅供参考 | StockStream AI",
                  font=small_font, fill=(139, 148, 158, 180))

        return np.array(img)

    def _render_slide_scene(self, scene: SceneType, width_px: int, height_px: int) -> np.ndarray:
        """Render an AI-generated slide as a scene.

        Maps SceneType to ai_slide_generator SlideType, fetches the rendered
        PNG from the slide generator cache, and returns it as RGBA.
        """
        # Lazy import to avoid circular dependency
        from stockstream.ai_slide_generator.models import SlideType as AISlideType

        _slide_map = {
            SceneType.SLIDE_OPEN: AISlideType.OPEN_POSITION,
            SceneType.SLIDE_ADD: AISlideType.ADD_POSITION,
            SceneType.SLIDE_REDUCE: AISlideType.REDUCE_POSITION,
            SceneType.SLIDE_CLEAR: AISlideType.CLEAR_POSITION,
            SceneType.SLIDE_RISK: AISlideType.RISK_WARNING,
        }
        slide_type = _slide_map.get(scene, AISlideType.RISK_WARNING)

        # Try to get the slide generator from the current service instance
        try:
            from stockstream.core.orchestrator import _current_services  # pyright: ignore[reportImportCycles]
            if _current_services and hasattr(_current_services, 'slide_generator'):
                generator = _current_services.slide_generator
                cache = generator._cache
                if slide_type in cache:
                    _, result = cache[slide_type]
                    if result.rgba is not None:
                        import cv2
                        target_rgba = cv2.resize(result.rgba, (width_px, height_px))
                        return target_rgba
        except Exception:
            pass

        # Fallback: dark placeholder with label
        import cv2
        placeholder = np.zeros((height_px, width_px, 4), dtype=np.uint8)
        placeholder[:, :, :3] = (13, 17, 23)
        placeholder[:, :, 3] = 255

        from PIL import Image, ImageDraw
        img = Image.fromarray(placeholder, mode="RGBA")
        draw = ImageDraw.Draw(img)
        try:
            from stockstream.video.subtitle_renderer import FONT_PATH
            from PIL import ImageFont
            font = ImageFont.truetype(FONT_PATH, 28) if FONT_PATH else ImageFont.load_default()
        except Exception:
            from PIL import ImageFont
            font = ImageFont.load_default()
        draw.text((width_px // 2 - 120, height_px // 2 - 20),
                  f"AI 选股幻灯片 — {scene.label}",
                  font=font, fill=(201, 209, 217, 255))
        draw.text((width_px // 2 - 160, height_px // 2 + 20),
                  "请先调用 POST /slide/generate 生成页面",
                  font=font, fill=(139, 148, 158, 200))

        return np.array(img)

    def _render_dashboard_scene(self, width_px: int, height_px: int) -> np.ndarray:
        """Render the full-screen financial dashboard as a scene.

        Fetches the latest RGBA from the DashboardEngine cache, resizes to
        the target dimensions, and returns it for compositing.
        """
        try:
            from stockstream.core.orchestrator import _current_services  # pyright: ignore[reportImportCycles]
            if _current_services and hasattr(_current_services, 'dashboard_engine'):
                engine = _current_services.dashboard_engine
                rgba = engine.rgba
                if rgba is not None:
                    import cv2
                    target = cv2.resize(rgba, (width_px, height_px))
                    return target
        except Exception:
            pass

        # Fallback: dark placeholder
        import cv2
        placeholder = np.zeros((height_px, width_px, 4), dtype=np.uint8)
        placeholder[:, :, :3] = (13, 17, 23)
        placeholder[:, :, 3] = 255

        from PIL import Image, ImageDraw
        img = Image.fromarray(placeholder, mode="RGBA")
        draw = ImageDraw.Draw(img)
        try:
            from stockstream.video.subtitle_renderer import FONT_PATH
            from PIL import ImageFont
            font = ImageFont.truetype(FONT_PATH, 28) if FONT_PATH else ImageFont.load_default()
        except Exception:
            from PIL import ImageFont
            font = ImageFont.load_default()
        draw.text((width_px // 2 - 140, height_px // 2 - 20),
                  "财经数据大屏",
                  font=font, fill=(201, 209, 217, 255))
        draw.text((width_px // 2 - 180, height_px // 2 + 20),
                  "Dashboard engine 未运行，请检查服务状态",
                  font=font, fill=(139, 148, 158, 200))

        return np.array(img)

    # ── helpers ──────────────────────────────────────────────────────

    def _get_renderer(self, width_px: int, height_px: int) -> StockChartRenderer:
        """Get or create a chart renderer for the given dimensions."""
        dpi = 100
        if self._chart_renderer is None:
            self._chart_renderer = StockChartRenderer(
                figsize=(width_px / dpi, height_px / dpi),
                dpi=dpi,
            )
        else:
            self._chart_renderer.figsize = (width_px / dpi, height_px / dpi)
            self._chart_renderer.dpi = dpi
        return self._chart_renderer

    def _score_rule(self, rule: _KeywordRule, text: str, text_lower: str) -> float:
        """Score a keyword rule against the given text.

        Uses a non-linear scoring approach:
            - Each keyword hit contributes weighted score
            - Regex hits are stronger signals (1.5x)
            - Score is normalized but boosted by keyword density
            - Higher priority rules get a small bonus

        Returns confidence 0.0–1.0.
        """
        hits = 0.0
        keyword_hits = 0

        # Keyword matching
        for kw in rule.keywords:
            kw_lower = kw.lower()
            if kw_lower in text_lower:
                # Longer keywords get higher weight
                weight = max(0.3, min(1.5, len(kw) / 4.0))
                hits += weight
                keyword_hits += 1

        # Regex matching (stronger signal)
        for pat in rule._compiled:
            if pat.search(text):
                hits += 2.0
                keyword_hits += 1

        if hits == 0:
            return 0.0

        # Confidence = base hit score normalized by a soft cap
        # plus keyword density bonus
        confidence = min(1.0, hits / 5.0)

        # Boost: more unique keyword hits = stronger confidence
        if keyword_hits >= 2:
            confidence = min(1.0, confidence + 0.2)

        # Priority bonus: higher priority scenes get a tiny edge
        confidence += (rule.priority / 1000.0)

        return min(1.0, confidence)

    def _has_data_for_scene(self, scene: SceneType) -> bool:
        """Check if we have the required data to render a scene."""
        d = self._data
        checks = {
            SceneType.KLINE: d.has_kline,
            SceneType.MINUTE: lambda: d.has_kline() or d.has_minute(),
            SceneType.VOLUME: d.has_kline,
            SceneType.MACD: lambda: len(d.macd_dif) >= 5,
            SceneType.RSI: lambda: len(d.rsi_values) >= 5,
            SceneType.FUND_FLOW: d.has_fund,
            SceneType.DRAGON_TIGER: d.has_dragon_tiger,
            SceneType.SECTOR_HEATMAP: d.has_sector,
            SceneType.ADVANCE_DECLINE: d.has_advance_decline,
            SceneType.AI_SUMMARY: d.has_ai_summary,
            SceneType.SLIDE_OPEN: lambda: True,     # always available (uses slide cache)
            SceneType.SLIDE_ADD: lambda: True,
            SceneType.SLIDE_REDUCE: lambda: True,
            SceneType.SLIDE_CLEAR: lambda: True,
            SceneType.SLIDE_RISK: lambda: True,
            SceneType.DASHBOARD: lambda: True,   # always available (uses dashboard cache)
        }
        checker = checks.get(scene, d.has_kline)
        try:
            return checker()
        except Exception:
            return False

    def _compute_indicators(self, kline_data: list[dict]) -> None:
        """Compute MACD and RSI indicators from kline data."""
        if len(kline_data) < 5:
            return

        closes = []
        for r in kline_data:
            p = r.get("payload", r)
            try:
                closes.append(float(p.get("收盘", p.get("close", 0))))
            except (ValueError, TypeError):
                closes.append(0.0)

        if len(closes) < 5:
            return

        closes_arr = np.array(closes, dtype=np.float64)

        # MACD (12, 26, 9)
        ema12 = _ema(closes_arr, 12)
        ema26 = _ema(closes_arr, 26)
        dif = ema12 - ema26
        dea = _ema(dif, 9)
        histogram = 2 * (dif - dea)

        self._data.macd_dif = dif.tolist()
        self._data.macd_dea = dea.tolist()
        self._data.macd_histogram = histogram.tolist()

        # RSI (14)
        self._data.rsi_values = _rsi(closes_arr, 14).tolist()


# ── indicator computation utilities ───────────────────────────────────────

def _ema(data: np.ndarray, period: int) -> np.ndarray:
    """Compute Exponential Moving Average."""
    if len(data) == 0:
        return np.array([])
    result = np.zeros_like(data)
    result[0] = data[0]
    alpha = 2.0 / (period + 1)
    for i in range(1, len(data)):
        result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
    return result


def _rsi(data: np.ndarray, period: int = 14) -> np.ndarray:
    """Compute Relative Strength Index."""
    if len(data) < period + 1:
        return np.full_like(data, 50.0)

    deltas = np.diff(data)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    avg_gain = np.zeros_like(data)
    avg_loss = np.zeros_like(data)
    avg_gain[period] = np.mean(gains[:period])
    avg_loss[period] = np.mean(losses[:period])

    for i in range(period + 1, len(data)):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i - 1]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i - 1]) / period

    rsi_values = np.full_like(data, 50.0)
    for i in range(period, len(data)):
        if avg_loss[i] == 0:
            rsi_values[i] = 100.0
        else:
            rs = avg_gain[i] / avg_loss[i]
            rsi_values[i] = 100.0 - (100.0 / (1.0 + rs))

    return rsi_values


def _wrap_text_pil(text: str, max_width: int, font, draw) -> list[str]:
    """Wrap text to fit within max_width pixels."""
    lines = []
    current = ""
    for ch in text:
        test = current + ch
        try:
            bbox = draw.textbbox((0, 0), test, font=font)
            w = bbox[2] - bbox[0]
        except Exception:
            w = len(test) * (font.size or 12) * 0.6
        if w > max_width and current:
            lines.append(current)
            current = ch
        else:
            current = test
    if current:
        lines.append(current)
    return lines or [text]


# ── factory ───────────────────────────────────────────────────────────────

def create_scene_manager() -> SceneManager:
    """Create a SceneManager with default settings."""
    return SceneManager()