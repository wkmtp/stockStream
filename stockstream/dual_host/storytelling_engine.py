"""Storytelling engine — translate technical indicators into everyday language.

Core capability: transform jargon like "MACD golden cross" into metaphors
that non-expert audiences can understand and enjoy.
"""

from __future__ import annotations

import random
import logging
from typing import Any

logger = logging.getLogger(__name__)


# ── Translation templates ──────────────────────────────────────

# Each indicator has multiple metaphors (randomly chosen for variety)

_MACD_GOLDEN_CROSS = [
    "就像汽车红灯变绿灯，上涨信号已经亮起来了",
    "可以理解成短线均线和长线均线手拉手往上走，技术面偏多",
    "在技术派眼里，这就像发动机点火了——短期动能已经超越长期动能",
]

_MACD_DEAD_CROSS = [
    "就像绿灯变红灯，短期趋势转弱了，需要等下一个绿灯",
    "在K线图上看，短线均线从上面穿破了长线均线，技术面短期承压",
    "好比运动员跑到一半体力不支了，需要休息调整一下",
]

_RSI_OVERBOUGHT = [
    "涨得太猛了，就像双十一抢购后的钱包——该歇歇了",
    "打个比方，就像爬山爬到了半山腰，需要喘口气继续爬还是下山",
    "市场兴奋过头了，不少人开始考虑落袋为安",
]

_RSI_OVERSOLD = [
    "就像超市大减价，很多人觉得便宜开始捡货了",
    "可能是因为大家恐慌卖得差不多了，有资金觉得这个位置可以进场",
    "相当于跌到地板价了，部分抄底资金开始试探性买入",
]

_MA_BREAK_UP = [
    "就像考及格了——股价已经站上了均线这个'及格线'，短期偏多",
    "股价突破了平均持仓成本，说明近期买入的人基本都赚钱了",
]

_MA_BREAK_DOWN = [
    "股价跌到均线下方，就像成绩从及格线掉下去了，短期承压",
    "最近一段时间买入的基本都在亏损，抛压可能会加重",
]

_VOLUME_SURGE = [
    "成交量大爆发，说明多空双方在激烈交锋，大家都在关注这个股票",
    "就像菜市场突然热闹起来，有买的也有卖的，说明有大资金在进出",
]

_VOLUME_SHRINK = [
    "交易非常冷清，说明大家都不敢动，观望情绪很重",
    "买卖双方都在观望，就像考试前的安静，大家都在等方向",
]

_INFLOW_POSITIVE = [
    "大资金今天在买货，相当于大户在囤货，说明他们看好后市",
    "主力资金在进场，相当于庄家开始收筹码了",
    "净流入说明今天买的力量大于卖的力量，资金面偏多",
]

_INFLOW_NEGATIVE = [
    "主力在减仓出货，说明大资金在这个位置有获利了结的想法",
    "资金在往外流出，相当于大户在悄悄撤退",
]

_CHANGE_UP = [
    "今天表现不错，涨了{:.1f}%，相当于买了100块赚了{}块",
    "涨了{:.1f}%，跑赢了大盘，说明有资金在关注",
]

_CHANGE_DOWN = [
    "今天跌了{:.1f}%，短期可能还要磨一磨",
    "回调了{:.1f}%，不过涨涨跌跌本来就很正常，关键看趋势",
]

_STOPPED = [
    "涨停了，说明买盘非常强，今天想买都买不进",
    "今天封涨停了，买一挂满了单子但就是买不到",
    "涨停就是当天涨幅到了上限，今天买方气势如虹，直接把价格打满了",
]

_LIMIT_DOWN = [
    "跌停了，说明今天卖压非常大，短期要小心",
    "跌停意味着当天跌幅已经到极限了，卖方不计成本在出货",
]

_SHRINKING_VOLUME = [
    "量能在缩，说明多空双方都不敢轻举妄动，都在等信号",
    "成交越来越清淡，就像暴风雨前的宁静",
    "缩量意味着市场在等一个方向选择，要么向上突破，要么向下调整",
]

_TURNOVER_HIGH = [
    "换手率很高，说明筹码在快速交换，今天进场的和出场的都很多",
    "高换手说明有人在出货也有人在接盘，多空分歧比较大",
]


class StorytellingEngine:
    """Translate technical indicators into plain, vivid language."""

    def translate_indicators(self, context: dict[str, Any]) -> list[str]:
        """Generate plain-language explanations for all indicators in context.

        Args:
            context: Analysis context dict from AnalysisService.

        Returns:
            List of human-readable explanations (2-4 items).
        """
        stories: list[str] = []

        # MACD
        if context.get("macd_golden_cross"):
            stories.append(random.choice(_MACD_GOLDEN_CROSS))
        if context.get("macd_dead_cross"):
            stories.append(random.choice(_MACD_DEAD_CROSS))

        # RSI
        rsi_val = context.get("rsi14")
        if rsi_val is not None:
            try:
                rsi_val = float(rsi_val)
                if rsi_val > 70:
                    stories.append(random.choice(_RSI_OVERBOUGHT))
                elif rsi_val < 30:
                    stories.append(random.choice(_RSI_OVERSOLD))
            except (TypeError, ValueError):
                pass

        # MA deviation
        ma20_dev = context.get("ma20_deviation_pct")
        if ma20_dev is not None:
            try:
                ma20_dev = float(ma20_dev)
                if ma20_dev > 3:
                    stories.append(random.choice(_MA_BREAK_UP))
                elif ma20_dev < -3:
                    stories.append(random.choice(_MA_BREAK_DOWN))
            except (TypeError, ValueError):
                pass

        # Volume
        if context.get("shrinking_volume"):
            stories.append(random.choice(_SHRINKING_VOLUME))

        # Turnover
        turnover = context.get("turnover_pct")
        if turnover is not None:
            try:
                turnover = float(turnover)
            except (TypeError, ValueError):
                pass
            else:
                if turnover > 10:
                    stories.append(random.choice(_TURNOVER_HIGH))

        # Change %
        change_pct = context.get("change_pct")
        if change_pct is not None:
            try:
                change_pct = float(change_pct)
            except (TypeError, ValueError):
                pass
            else:
                if change_pct >= 9.5:
                    stories.append(random.choice(_STOPPED))
                elif change_pct <= -9.5:
                    stories.append(random.choice(_LIMIT_DOWN))
                elif change_pct > 0:
                    stories.append(random.choice(_CHANGE_UP).format(
                        change_pct, f"{change_pct*10:.0f}"))
                elif change_pct < 0:
                    stories.append(random.choice(_CHANGE_DOWN).format(change_pct))

        # Fund flow
        inflow = context.get("main_inflow")
        if inflow is not None:
            try:
                inflow = float(inflow)
                if inflow > 5e7:  # > 5000万
                    yi = inflow / 1e8
                    stories.append(f"主力资金今天净流入{yi:.1f}亿，可以理解成大资金在进场买货")
                elif inflow < -5e7:
                    yi = abs(inflow) / 1e8
                    stories.append(f"主力资金今天净流出{yi:.1f}亿，说明有大资金在减仓")
            except (TypeError, ValueError):
                pass

        # Limit to 4 stories to keep dialogue concise
        return stories[:4]

    def explain_single(self, indicator: str, value: Any = None) -> str:
        """Translate a single indicator by name.

        Args:
            indicator: Indicator name (e.g. 'macd_golden_cross', 'rsi_oversold').
            value: Optional numeric value.

        Returns:
            Plain-language explanation.
        """
        templates = {
            "macd_golden_cross": _MACD_GOLDEN_CROSS,
            "macd_dead_cross": _MACD_DEAD_CROSS,
            "rsi_overbought": _RSI_OVERBOUGHT,
            "rsi_oversold": _RSI_OVERSOLD,
            "volume_surge": _VOLUME_SURGE,
            "volume_shrink": _VOLUME_SHRINK,
            "inflow_positive": _INFLOW_POSITIVE,
            "inflow_negative": _INFLOW_NEGATIVE,
            "shrinking_volume": _SHRINKING_VOLUME,
            "limit_up": _STOPPED,
            "limit_down": _LIMIT_DOWN,
        }
        pool = templates.get(indicator, ["这个指标有点复杂，简单来说就是市场在发生变化"])
        return random.choice(pool)
