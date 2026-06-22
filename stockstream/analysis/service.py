"""Analysis service — orchestrates rule engine + DeepSeek API for 主播口播文案.

Three input modes:
    1. stock  → 股票名或股票代码
    2. sector → 板块名称
    3. market → 大盘分析

Two execution paths:
    - 规则引擎（本地，零延迟）：当市场数据充足时，用模板直接生成文案。
    - DeepSeek API（云端）：当规则引擎上下文不足时，或显式指定时，调用 LLM。

Usage::

    svc = AnalysisService(api_key="sk-...", market_storage=storage)
    result = await svc.analyze("贵州茅台", mode="stock", engine="auto")
    print(result.script)  # 200字以内口播文案
"""

from __future__ import annotations

import logging
from typing import Any

from stockstream.analysis.engine import build_commentary
from stockstream.analysis.models import (
    AnalysisEngine,
    AnalysisResult,
    AnalysisType,
    StockContext,
)
from stockstream.analysis.prompts import DeepSeekClient, market_prompt, sector_prompt, stock_prompt
from stockstream.market.models import MarketDataset, StockSymbol
from stockstream.market.storage import MarketSQLiteStorage
from stockstream.selector.indicators import (
    is_shrinking_volume,
    macd_cross,
    rsi,
    simple_moving_average,
)

logger = logging.getLogger(__name__)


class AnalysisService:
    """Main entry point for generating 主播口播文案."""

    def __init__(
        self,
        api_key: str = "",
        market_storage: MarketSQLiteStorage | None = None,
    ) -> None:
        self.llm = DeepSeekClient(api_key=api_key)
        self.storage = market_storage or MarketSQLiteStorage()

    # ── public API ─────────────────────────────────────────────────

    async def analyze(
        self,
        query: str,
        *,
        mode: str = "stock",
        engine: str = "auto",
    ) -> AnalysisResult:
        """Analyze and produce a commentary script.

        Args:
            query: 股票名/代码、板块名、或 "大盘".
            mode: "stock" | "sector" | "market".
            engine: "auto" | "rules" | "deepseek".
                "auto" tries rules first; falls back to DeepSeek.

        Returns:
            AnalysisResult with the generated script.
        """
        analysis_type = _parse_analysis_type(mode)
        engine_choice = _parse_engine(engine)

        # 1. 尝试规则引擎
        if engine_choice in (AnalysisEngine.RULES, None):
            try:
                context = await self._build_context(query, analysis_type)
                if context:
                    result = build_commentary(analysis_type, context)
                    if engine_choice is AnalysisEngine.RULES or self._is_script_adequate(result.script):
                        return result
            except Exception:
                logger.debug("Rules engine failed for %s, falling back to DeepSeek", query)

        # 2. 回退到 DeepSeek
        if self.llm.available():
            return await self._deepseek_analyze(query, analysis_type)

        # 3. 最终降级：返回简单规则文案
        return build_commentary(analysis_type, {"query": query})

    async def analyze_stock(self, symbol_or_name: str) -> AnalysisResult:
        """Shortcut: analyze a single stock."""
        return await self.analyze(symbol_or_name, mode="stock")

    async def analyze_sector(self, sector_name: str) -> AnalysisResult:
        """Shortcut: analyze a sector."""
        return await self.analyze(sector_name, mode="sector")

    async def analyze_market(self) -> AnalysisResult:
        """Shortcut: analyze the overall market."""
        return await self.analyze("大盘", mode="market")

    # ── context builders ───────────────────────────────────────────

    async def _build_context(
        self, query: str, analysis_type: AnalysisType
    ) -> dict[str, Any] | None:
        """Build structured context from cached market data."""
        if analysis_type is AnalysisType.STOCK:
            return await self._build_stock_context(query)
        if analysis_type is AnalysisType.SECTOR:
            return await self._build_sector_context(query)
        if analysis_type is AnalysisType.MARKET:
            return await self._build_market_context()
        return None

    async def _build_stock_context(self, query: str) -> dict[str, Any] | None:
        """Build StockContext from cached spot + fund_flow + daily data."""
        code = _normalize_code(query)
        stock = StockSymbol.from_code(code)

        # Load data from cache
        spot = await self._latest_spot_for_symbol(stock.code)
        fund = await self._latest_fund_flow_for_symbol(stock.code)
        daily = await self._daily_series_for_symbol(stock.code)

        if not spot and not daily:
            logger.debug("No cached data for %s", stock.code)
            return None

        closes = _extract_closes(daily)
        volumes = _extract_volumes(daily)
        close = _safe_float(spot, "最新价") or (closes[-1] if closes else None)
        if close is None:
            return None

        ma20 = simple_moving_average(closes, 20)
        ma60 = simple_moving_average(closes, 60)
        ma20_dev = ((close - ma20) / ma20 * 100) if ma20 else None
        macd_diff, macd_sig, golden, dead = macd_cross(closes)

        ctx = {
            "query": query,
            "symbol": stock.code,
            "name": _safe_text(spot, "名称") or _safe_text(fund, "股票简称") or query,
            "close": close,
            "change_pct": _safe_float(spot, "涨跌幅"),
            "ma20": ma20,
            "ma60": ma60,
            "ma20_deviation_pct": ma20_dev,
            "macd_diff": macd_diff,
            "macd_signal": macd_sig,
            "macd_golden_cross": golden,
            "macd_dead_cross": dead,
            "rsi14": rsi(closes),
            "turnover_pct": _safe_float(spot, "换手率"),
            "main_inflow": _safe_float(fund, "主力净流入-净额") or _safe_float(fund, "主力净流入净额"),
            "main_inflow_pct": _safe_float(fund, "主力净流入-净占比") or _safe_float(fund, "主力净流入净占比"),
            "super_large_inflow": _safe_float(fund, "超大单净流入-净额"),
            "large_inflow": _safe_float(fund, "大单净流入-净额"),
            "shrinking_volume": is_shrinking_volume(volumes),
        }
        return ctx

    async def _build_sector_context(self, query: str) -> dict[str, Any] | None:
        """Build SectorContext.  Limited by available data — AkShare sectors
        require separate board APIs; we provide a minimal context here."""
        # 从 spot 数据中尝试推断板块信息（基于名称匹配）
        # 如果无法从缓存获取，返回 None 让 DeepSeek 处理
        return {
            "query": query,
            "name": query,
        }

    async def _build_market_context(self) -> dict[str, Any] | None:
        """Build MarketContext from spot cache aggregates."""
        rows = await self.storage.latest(MarketDataset.SPOT, limit=5000)
        if not rows:
            return None

        up = down = flat = 0
        changes: list[float] = []
        for row in rows:
            pct = _safe_float(row.get("payload", {}), "涨跌幅")
            if pct is not None:
                changes.append(pct)
                if pct > 0:
                    up += 1
                elif pct < 0:
                    down += 1
                else:
                    flat += 1

        avg_change = sum(changes) / len(changes) if changes else None

        return {
            "query": "大盘",
            "up_count": up,
            "down_count": down,
            "flat_count": flat,
            "avg_change_pct": avg_change,
        }

    # ── DeepSeek path ──────────────────────────────────────────────

    async def _deepseek_analyze(
        self, query: str, analysis_type: AnalysisType
    ) -> AnalysisResult:
        """Call DeepSeek API with structured context."""
        context = {}
        try:
            context = await self._build_context(query, analysis_type) or {}
        except Exception:
            context = {"query": query}

        # Build prompt
        if analysis_type is AnalysisType.STOCK:
            prompt = stock_prompt(context)
        elif analysis_type is AnalysisType.SECTOR:
            prompt = sector_prompt(context)
        else:
            prompt = market_prompt(context)

        try:
            script, tokens = await self.llm.chat(prompt)
            logger.info("DeepSeek produced %d-char script (%d tokens)", len(script), tokens)
        except Exception as exc:
            logger.warning("DeepSeek API failed: %s, falling back to rules", exc)
            return build_commentary(analysis_type, {"query": query})

        # Truncate to 200 chars
        if len(script) > 200:
            script = script[:197] + "..."

        return AnalysisResult(
            analysis_type=analysis_type,
            engine=AnalysisEngine.DEEPSEEK,
            script=script,
            query=query,
            context=context,
            token_count=tokens,
        )

    # ── cache helpers ──────────────────────────────────────────────

    async def _latest_spot_for_symbol(self, code: str) -> dict[str, Any] | None:
        rows = await self.storage.symbol_history(MarketDataset.SPOT, code, limit=1)
        return rows[0].get("payload") if rows else None

    async def _latest_fund_flow_for_symbol(self, code: str) -> dict[str, Any] | None:
        rows = await self.storage.symbol_history(MarketDataset.FUND_FLOW, code, limit=1)
        return rows[0].get("payload") if rows else None

    async def _daily_series_for_symbol(self, code: str) -> list[dict[str, Any]]:
        rows = await self.storage.symbol_history(MarketDataset.DAILY, code, limit=200)
        return [r.get("payload", {}) for r in rows]

    def _is_script_adequate(self, script: str) -> bool:
        """Heuristic: a rules-generated script is adequate if it's informative."""
        return len(script) >= 20 and "未获取" not in script


# ── module-level helpers ────────────────────────────────────────────────


def _parse_analysis_type(mode: str) -> AnalysisType:
    mode_lower = mode.lower()
    if mode_lower in ("stock", "个股", "股票"):
        return AnalysisType.STOCK
    if mode_lower in ("sector", "板块", "行业"):
        return AnalysisType.SECTOR
    if mode_lower in ("market", "大盘", "市场"):
        return AnalysisType.MARKET
    return AnalysisType.STOCK  # default


def _parse_engine(engine: str) -> AnalysisEngine | None:
    engine_lower = engine.lower()
    if engine_lower == "rules":
        return AnalysisEngine.RULES
    if engine_lower == "deepseek":
        return AnalysisEngine.DEEPSEEK
    return None  # "auto" → None signals try-rules-then-fallback


def _normalize_code(query: str) -> str:
    """Normalize a query into a 6-digit stock code if possible."""
    import re
    match = re.search(r"\d{6}", query)
    if match:
        return match.group()
    return query.strip()


def _safe_float(row: dict[str, Any] | None, key: str) -> float | None:
    if not row:
        return None
    val = row.get(key)
    if val in (None, "", "-"):
        return None
    try:
        if isinstance(val, str):
            val = val.replace(",", "").replace("%", "")
        return float(val)
    except (TypeError, ValueError):
        return None


def _safe_text(row: dict[str, Any] | None, key: str) -> str | None:
    if not row:
        return None
    val = row.get(key)
    return str(val) if val not in (None, "") else None


def _extract_closes(daily: list[dict[str, Any]]) -> list[float]:
    values = [_safe_float(row, "收盘") or _safe_float(row, "close") for row in daily]
    return [v for v in values if v is not None]


def _extract_volumes(daily: list[dict[str, Any]]) -> list[float]:
    values = [_safe_float(row, "成交量") or _safe_float(row, "volume") for row in daily]
    return [v for v in values if v is not None]
