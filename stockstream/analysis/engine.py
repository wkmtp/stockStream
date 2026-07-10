"""Rule-based commentary engine.

Produces主播口播文案 from structured market context using deterministic
templates and conditional logic — no LLM call required.  Falls back to
DeepSeek when the context is rich enough to warrant a nuanced summary.
"""

from __future__ import annotations

import logging
from typing import Any

from stockstream.analysis.models import (
    AnalysisEngine,
    AnalysisResult,
    AnalysisType,
    MarketContext,
    SectorContext,
    StockContext,
)

logger = logging.getLogger(__name__)

# ── helpers ────────────────────────────────────────────────────────────


def _fmt_inflow(amount: float | None) -> str:
    """Format a net-inflow number into a human-readable Chinese string."""
    if amount is None:
        return "资金面平淡"
    abs_val = abs(amount)
    if abs_val >= 1e8:
        direction = "净流入" if amount > 0 else "净流出"
        return f"主力{direction}{abs_val / 1e8:.2f}亿"
    if abs_val >= 1e4:
        direction = "净流入" if amount > 0 else "净流出"
        return f"主力{direction}{abs_val / 1e4:.0f}万"
    direction = "净流入" if amount > 0 else "净流出"
    return f"主力{direction}{abs_val:.0f}元"


def _fmt_change(change_pct: float | None) -> str:
    """Format a percentage change with direction."""
    if change_pct is None:
        return "涨跌幅未获取"
    if change_pct > 0:
        return f"涨{change_pct:.2f}%"
    if change_pct < 0:
        return f"跌{abs(change_pct):.2f}%"
    return "平盘"


def _signal_suggestion(ctx: StockContext) -> str:
    """Derive a brief trading suggestion from indicator signals."""
    parts: list[str] = []
    if ctx.macd_golden_cross:
        parts.append("MACD金叉确认")
    if ctx.macd_dead_cross:
        parts.append("MACD死叉警示")
    if ctx.rsi14 is not None:
        if ctx.rsi14 > 70:
            parts.append("RSI超买，注意回调风险")
        elif ctx.rsi14 < 30:
            parts.append("RSI超卖，关注反弹机会")
    if ctx.ma20_deviation_pct is not None:
        if ctx.ma20_deviation_pct > 10:
            parts.append("偏离MA20过大，仓位宜轻")
        elif ctx.ma20_deviation_pct < -8:
            parts.append("大幅低于MA20，可关注企稳信号")
    if ctx.shrinking_volume:
        parts.append("缩量整理")
    if not parts:
        parts.append("建议观望")
    return "，".join(parts)


# ── stock commentary ───────────────────────────────────────────────────


def _build_stock_script(ctx: StockContext) -> str:
    """Produce a ≤200-char commentary for a single stock."""
    name = ctx.name or ctx.symbol

    lines: list[str] = []
    # Line 1: 涨跌 + 资金
    inflow_text = _fmt_inflow(ctx.main_inflow)
    change_text = _fmt_change(ctx.change_pct)
    lines.append(f"{name}今日{change_text}，{inflow_text}。")

    # Line 2: 技术信号 + 建议
    suggestion = _signal_suggestion(ctx)
    lines.append(f"{suggestion}。")

    # Line 3: 补充数据（换手率、偏离）
    extras: list[str] = []
    if ctx.turnover_pct is not None:
        extras.append(f"换手率{ctx.turnover_pct:.2f}%")
    if ctx.ma20_deviation_pct is not None:
        direction = "上方" if ctx.ma20_deviation_pct > 0 else "下方"
        extras.append(f"位于MA20{direction}{abs(ctx.ma20_deviation_pct):.1f}%")
    if extras:
        lines.append("，".join(extras) + "。")

    script = "".join(lines)
    if len(script) > 200:
        script = script[:197] + "..."
    return script


# ── sector commentary ──────────────────────────────────────────────────


def _build_sector_script(ctx: SectorContext) -> str:
    """Produce a ≤200-char commentary for a sector / 板块."""
    name = ctx.name

    lines: list[str] = []

    # Line 1: 整体描述
    change_text = _fmt_change(ctx.change_pct)
    ratio = f"{ctx.up_count}涨{ctx.down_count}跌" if ctx.up_count or ctx.down_count else ""
    lines.append(f"今日{name}整体{change_text}")

    if ctx.main_inflow is not None:
        lines.append(f"，{_fmt_inflow(ctx.main_inflow)}")
    lines.append("。")

    # Line 2: 分化 + 领涨领跌
    if ratio:
        parts = [ratio]
        if ctx.leading_stocks:
            parts.append(f"领涨：{'、'.join(ctx.leading_stocks[:3])}")
        if ctx.lagging_stocks:
            parts.append(f"领跌：{'、'.join(ctx.lagging_stocks[:3])}")
        lines.append("，".join(parts) + "。")

    # Line 3: 操作建议
    if ctx.change_pct is not None and ctx.change_pct > 2:
        lines.append("板块景气上行可逢低关注，仓位不宜过重。")
    elif ctx.change_pct is not None and ctx.change_pct < -2:
        lines.append("板块仍处探底阶段，等待企稳信号再做判断。")
    else:
        lines.append("板块内部分化明显，精选个股，轻仓参与。")

    script = "".join(lines)
    if len(script) > 200:
        script = script[:197] + "..."
    return script


# ── market commentary ──────────────────────────────────────────────────


def _build_market_script(ctx: MarketContext) -> str:
    """Produce a ≤200-char market overview commentary."""
    lines: list[str] = []

    # Line 1: 涨跌家数 + 平均涨跌
    if ctx.up_count or ctx.down_count:
        ratio = f"全市场{ctx.up_count}家上涨、{ctx.down_count}家下跌"
        if ctx.avg_change_pct is not None:
            ratio += f"，平均涨跌幅{ctx.avg_change_pct:+.2f}%"
        lines.append(ratio + "。")

    # Line 2: 资金面
    if ctx.main_inflow_total is not None:
        lines.append(_fmt_inflow(ctx.main_inflow_total) + "。")

    # Line 3: 热点
    if ctx.hotspot_summary:
        lines.append(ctx.hotspot_summary + "。")
    elif ctx.top_sectors:
        lines.append(f"领涨板块：{'、'.join(ctx.top_sectors[:3])}。")

    if ctx.bottom_sectors:
        lines.append(f"领跌板块：{'、'.join(ctx.bottom_sectors[:3])}。")

    # Line 4: 建议
    if ctx.up_count > ctx.down_count * 2:
        lines.append("市场情绪偏暖，可适度参与主线方向。")
    elif ctx.down_count > ctx.up_count * 2:
        lines.append("市场情绪偏冷，建议控制仓位，多看少动。")
    else:
        lines.append("市场分化震荡，选对方向比择时更重要。")

    script = "".join(lines)
    if len(script) > 200:
        script = script[:197] + "..."
    return script


# ── unified entry ──────────────────────────────────────────────────────


def build_commentary(
    analysis_type: AnalysisType,
    context: dict[str, Any],
) -> AnalysisResult:
    """Build a commentary script using rules only (no API call).

    Args:
        analysis_type: stock / sector / market.
        context: Structured context dict matching the analysis type.

    Returns:
        AnalysisResult with engine=AnalysisEngine.RULES.
    """
    query = context.get("query", "")

    if analysis_type is AnalysisType.STOCK:
        stock_ctx = _stock_context_from_dict(context)
        script = _build_stock_script(stock_ctx)
        ctx_dict = stock_ctx.to_dict()
    elif analysis_type is AnalysisType.SECTOR:
        sector_ctx = _sector_context_from_dict(context)
        script = _build_sector_script(sector_ctx)
        ctx_dict = sector_ctx.to_dict()
    elif analysis_type is AnalysisType.MARKET:
        market_ctx = _market_context_from_dict(context)
        script = _build_market_script(market_ctx)
        ctx_dict = market_ctx.to_dict()
    else:
        script = "无法识别分析类型，请提供股票、板块或大盘信息。"
        ctx_dict = {}

    logger.info(
        "Rules engine produced %d-char script for %s",
        len(script), analysis_type.value,
    )
    return AnalysisResult(
        analysis_type=analysis_type,
        engine=AnalysisEngine.RULES,
        script=script,
        query=query,
        context=ctx_dict,
        token_count=0,
    )


# ── context builders from raw dict ─────────────────────────────────────


def _stock_context_from_dict(data: dict[str, Any]) -> StockContext:
    return StockContext(
        symbol=data.get("symbol", ""),
        name=data.get("name", ""),
        close=_float_or_none(data, "close"),
        change_pct=_float_or_none(data, "change_pct"),
        ma20=_float_or_none(data, "ma20"),
        ma60=_float_or_none(data, "ma60"),
        ma20_deviation_pct=_float_or_none(data, "ma20_deviation_pct"),
        macd_diff=_float_or_none(data, "macd_diff"),
        macd_signal=_float_or_none(data, "macd_signal"),
        macd_golden_cross=bool(data.get("macd_golden_cross", False)),
        macd_dead_cross=bool(data.get("macd_dead_cross", False)),
        rsi14=_float_or_none(data, "rsi14"),
        turnover_pct=_float_or_none(data, "turnover_pct"),
        main_inflow=_float_or_none(data, "main_inflow"),
        main_inflow_pct=_float_or_none(data, "main_inflow_pct"),
        super_large_inflow=_float_or_none(data, "super_large_inflow"),
        large_inflow=_float_or_none(data, "large_inflow"),
        shrinking_volume=bool(data.get("shrinking_volume", False)),
    )


def _sector_context_from_dict(data: dict[str, Any]) -> SectorContext:
    return SectorContext(
        name=data.get("name", ""),
        change_pct=_float_or_none(data, "change_pct"),
        up_count=int(data.get("up_count", 0)),
        down_count=int(data.get("down_count", 0)),
        main_inflow=_float_or_none(data, "main_inflow"),
        leading_stocks=tuple(data.get("leading_stocks", ())),
        lagging_stocks=tuple(data.get("lagging_stocks", ())),
        summary=str(data.get("summary", "")),
    )


def _market_context_from_dict(data: dict[str, Any]) -> MarketContext:
    return MarketContext(
        up_count=int(data.get("up_count", 0)),
        down_count=int(data.get("down_count", 0)),
        flat_count=int(data.get("flat_count", 0)),
        avg_change_pct=_float_or_none(data, "avg_change_pct"),
        total_turnover=_float_or_none(data, "total_turnover"),
        top_sectors=tuple(data.get("top_sectors", ())),
        bottom_sectors=tuple(data.get("bottom_sectors", ())),
        main_inflow_total=_float_or_none(data, "main_inflow_total"),
        hotspot_summary=str(data.get("hotspot_summary", "")),
    )


def _float_or_none(data: dict[str, Any], key: str) -> float | None:
    val = data.get(key)
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
