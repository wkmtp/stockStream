"""Slide Generator — converts SelectorReport into PPT-style financial slide pages.

Core pipeline:
    1. Receive SelectorReport from SelectorService
    2. Build SlideData for each signal category (open/add/reduce/clear)
    3. Render each SlideData as a professional PNG via SlideRenderer
    4. Cache results for digital human livestream scene switching

Usage::

    generator = SlideGenerator(selector_service)
    # Generate all slides from latest selector report:
    results = await generator.generate_all()
    # results = {"open_position": SlideResult, "add_position": SlideResult, ...}

    # Get a single slide by type:
    slide_rgba = await generator.get_slide("open_position")

    # Generate slides for a specific stock:
    slide = await generator.generate_single("open_position", stock_cards=[...])

    # Cache management:
    generator.invalidate_cache()
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from stockstream.ai_slide_generator.models import (
    SlideConfig,
    SlideData,
    SlideResult,
    SlideTemplate,
    SlideType,
    StockSlideCard,
    OpenPositionSlide,
    AddPositionSlide,
    ReducePositionSlide,
    ClearPositionSlide,
    RiskWarningSlide,
)
from stockstream.ai_slide_generator.renderer import SlideRenderer, _SLIDE_TEMPLATES
from stockstream.selector.models import SelectorReport, SignalCandidate, SignalType

logger = logging.getLogger(__name__)


# ── Risk warning text (configurable) ────────────────────────────────────

_DEFAULT_RISK_TEXT = (
    "⚠ 重要风险提示\n\n"
    "1. 市场风险：股票市场存在系统性风险，受宏观经济、政策调控、国际形势等多重因素影响，"
    "价格波动具有不可预测性。\n\n"
    "2. 个股风险：单只股票可能面临公司经营、行业周期、突发事件等非系统性风险，"
    "需分散投资降低集中度。\n\n"
    "3. 策略风险：AI 选股模型基于历史数据和技术指标，不保证未来收益，"
    "历史回测表现不代表实际投资收益。\n\n"
    "4. 流动性风险：部分小盘股或低换手率股票可能存在流动性不足的风险，"
    "大额交易可能产生较大冲击成本。\n\n"
    "5. 操作风险：建仓/补仓/减仓/清仓信号仅供参考，投资者应结合自身"
    "风险承受能力和投资目标独立决策。\n\n"
    "投资有风险，入市需谨慎。以上内容由 AI 自动生成，不构成投资建议。"
)


# ── Slide builder ───────────────────────────────────────────────────────

@dataclass
class _SlideBuildContext:
    """Internal context for building slides from a selector report."""

    evaluated: int = 0
    generated_at: str = ""
    market_summary: str = ""


class SlideGenerator:
    """Converts SelectorReport signals into rendered PPT-style slide pages.

    Features:
        - Auto-generate 5 slide types from SelectorReport
        - Per-slide cache with TTL
        - Individual slide query by type
        - Risk warning standalone slide
        - PNG file export
    """

    def __init__(
        self,
        selector=None,  # SelectorService (optional, for auto-fetch)
        config: SlideConfig | None = None,
        cache_ttl_sec: float = 60.0,
        risk_text: str = "",
        output_dir: str = "cache/slides",
    ) -> None:
        self._selector = selector
        self._renderer = SlideRenderer(config=config)
        self._cache_ttl = cache_ttl_sec
        self._risk_text = risk_text or _DEFAULT_RISK_TEXT
        self._output_dir = output_dir

        # Cache: {SlideType → (timestamp, SlideResult)}
        self._cache: dict[SlideType, tuple[float, SlideResult]] = {}
        self._last_report: Optional[SelectorReport] = None

        # Stats
        self._generation_count: int = 0
        self._last_generation_time: float = 0.0
        self._errors: int = 0

    # ── Public API ──────────────────────────────────────────────────

    async def generate_all(
        self,
        report: SelectorReport | None = None,
        force: bool = False,
    ) -> dict[str, SlideResult]:
        """Generate all 5 slide types from a SelectorReport.

        Args:
            report: Optional SelectorReport. If None, auto-fetch from selector.
            force: If True, skip cache and regenerate all slides.

        Returns:
            Dict mapping slide_type string → SlideResult.
        """
        if not force and self._is_cache_valid():
            return {k.value: v for k, (_, v) in self._cache.items()}

        t_start = time.perf_counter()

        if report is None and self._selector is not None:
            report = await self._selector.generate_signals(top_n=10)

        if report is None:
            logger.warning("No SelectorReport available, generating only risk warning")
            risk_result = self._render_risk_slide()
            self._cache = {SlideType.RISK_WARNING: (time.monotonic(), risk_result)}
            self._generation_count += 1
            self._last_generation_time = (time.perf_counter() - t_start) * 1000.0
            return {"risk_warning": risk_result}

        self._last_report = report

        ctx = _SlideBuildContext(
            evaluated=report.evaluated,
            generated_at=datetime.now(timezone.utc).isoformat(),
            market_summary=f"全市场评估 {report.evaluated} 只标的",
        )

        results: dict[str, SlideResult] = {}

        # Build and render each slide type
        slide_types = [
            (SlideType.OPEN_POSITION, report.top10_open),
            (SlideType.ADD_POSITION, report.top10_add),
            (SlideType.REDUCE_POSITION, report.top10_reduce),
            (SlideType.CLEAR_POSITION, report.top10_clear),
        ]

        for slide_type, candidates in slide_types:
            slide_data = self._build_slide_data(slide_type, candidates, ctx)
            result = self._renderer.render(slide_data)
            self._cache[slide_type] = (time.monotonic(), result)
            results[slide_type.value] = result

        # Risk warning (always generated)
        risk_result = self._render_risk_slide()
        self._cache[SlideType.RISK_WARNING] = (time.monotonic(), risk_result)
        results["risk_warning"] = risk_result

        self._generation_count += 1
        self._last_generation_time = (time.perf_counter() - t_start) * 1000.0

        logger.info("Generated %d slides in %.1f ms (evaluated=%d stocks)",
                     len(results), self._last_generation_time, report.evaluated)

        return results

    async def get_slide(
        self,
        slide_type: str,
        report: SelectorReport | None = None,
    ) -> SlideResult | None:
        """Get a single slide by type name. Uses cache if available.

        Args:
            slide_type: "open_position", "add_position", "reduce_position",
                        "clear_position", or "risk_warning".
            report: Optional report to use for generation.

        Returns:
            SlideResult or None if slide_type is invalid.
        """
        try:
            st = SlideType(slide_type)
        except ValueError:
            logger.warning("Unknown slide type: %s", slide_type)
            return None

        # Check cache
        if self._is_cache_valid() and st in self._cache:
            _, result = self._cache[st]
            return result

        # Generate
        results = await self.generate_all(report=report)
        return results.get(slide_type)

    async def generate_single(
        self,
        slide_type: str,
        stock_cards: list[StockSlideCard],
        title: str = "",
        subtitle: str = "",
        extra_note: str = "",
    ) -> SlideResult:
        """Generate a single slide with custom stock cards.

        Args:
            slide_type: Slide type name.
            stock_cards: List of StockSlideCard objects.
            title: Optional custom title.
            subtitle: Optional custom subtitle.
            extra_note: Optional timestamp/note.

        Returns:
            SlideResult.
        """
        try:
            st = SlideType(slide_type)
        except ValueError:
            st = SlideType.RISK_WARNING

        template = _SLIDE_TEMPLATES.get(st, RiskWarningSlide)

        slide_data = SlideData(
            slide_type=st,
            title=title or f"{template.title_prefix} Top{len(stock_cards)}",
            subtitle=subtitle,
            cards=stock_cards,
            generated_at=datetime.now(timezone.utc).isoformat(),
            extra_note=extra_note,
        )

        result = self._renderer.render(slide_data)
        self._cache[st] = (time.monotonic(), result)
        return result

    def invalidate_cache(self) -> None:
        """Clear the slide cache."""
        self._cache.clear()
        logger.info("Slide cache invalidated")

    # ── Properties ──────────────────────────────────────────────────

    @property
    def stats(self) -> dict:
        return {
            "generation_count": self._generation_count,
            "last_generation_time_ms": round(self._last_generation_time, 2),
            "errors": self._errors,
            "cached_slides": list(k.value for k in self._cache),
            "cache_ttl_sec": self._cache_ttl,
            "evaluated_stocks": self._last_report.evaluated if self._last_report else 0,
        }

    @property
    def cached_slide_types(self) -> list[str]:
        return [k.value for k in self._cache]

    # ── Export ──────────────────────────────────────────────────────

    def export_slides(self, results: dict[str, SlideResult],
                      prefix: str = "slide") -> dict[str, str]:
        """Export all slides to PNG files. Returns {slide_type: filepath}."""
        import os
        os.makedirs(self._output_dir, exist_ok=True)

        paths: dict[str, str] = {}
        for st_name, result in results.items():
            filename = f"{prefix}_{st_name}.png"
            filepath = os.path.join(self._output_dir, filename)
            result.to_png_file(filepath)
            paths[st_name] = filepath
            logger.info("Exported slide: %s", filepath)

        return paths

    # ── Internal helpers ────────────────────────────────────────────

    def _is_cache_valid(self) -> bool:
        if not self._cache:
            return False
        now = time.monotonic()
        # All cached entries must be fresh
        for _, (ts, _) in self._cache.items():
            if now - ts > self._cache_ttl:
                return False
        return True

    def _build_slide_data(
        self,
        slide_type: SlideType,
        candidates: tuple[SignalCandidate, ...] | list[SignalCandidate],
        ctx: _SlideBuildContext,
    ) -> SlideData:
        """Build SlideData from SignalCandidate list."""
        template = _SLIDE_TEMPLATES.get(slide_type, RiskWarningSlide)

        cards: list[StockSlideCard] = []
        for i, candidate in enumerate(candidates[:10]):
            card = StockSlideCard(
                symbol=candidate.symbol,
                name=candidate.name or candidate.symbol,
                close=candidate.close,
                ma20=candidate.ma20,
                ma20_deviation_pct=candidate.ma20_deviation_pct,
                daily_change_pct=candidate.daily_change_pct,
                turnover_pct=candidate.turnover_pct,
                money_flow=candidate.money_flow,
                institutional_money_flow=candidate.institutional_money_flow,
                rsi14=candidate.rsi14,
                reasons=candidate.reasons,
                rank=i + 1,
            )
            cards.append(card)

        count = len(cards)
        title = f"{template.title_prefix} Top{min(count, 10)}"
        subtitle = f"共筛选出 {count} 只标的" if count > 0 else "暂无符合条件的标的"

        return SlideData(
            slide_type=slide_type,
            title=title,
            subtitle=subtitle,
            cards=cards,
            generated_at=ctx.generated_at,
            market_summary=ctx.market_summary,
            extra_note=f"数据刷新于 {datetime.now().strftime('%H:%M:%S')}",
        )

    def _render_risk_slide(self) -> SlideResult:
        """Render the standalone risk warning slide."""
        slide_data = SlideData(
            slide_type=SlideType.RISK_WARNING,
            title="🛡 风险提示与免责声明",
            subtitle="投资决策前请仔细阅读",
            risk_text=self._risk_text,
            generated_at=datetime.now(timezone.utc).isoformat(),
            market_summary="重要须知",
        )
        return self._renderer.render(slide_data)


# ── Factory ─────────────────────────────────────────────────────────────

def create_slide_generator(
    selector=None,
    config: SlideConfig | None = None,
    cache_ttl_sec: float = 60.0,
    risk_text: str = "",
    output_dir: str = "cache/slides",
) -> SlideGenerator:
    """Create a SlideGenerator with default settings.

    Args:
        selector: Optional SelectorService for auto-fetching reports.
        config: Optional SlideConfig for custom rendering.
        cache_ttl_sec: Cache TTL in seconds (default 60s).
        risk_text: Custom risk warning text.
        output_dir: Directory for exported PNG files.

    Returns:
        Configured SlideGenerator instance.
    """
    return SlideGenerator(
        selector=selector,
        config=config,
        cache_ttl_sec=cache_ttl_sec,
        risk_text=risk_text,
        output_dir=output_dir,
    )
