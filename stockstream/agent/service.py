"""Decision agent — coordinates selector, trader, TTS, and the auto-trading pipeline.

AgentService is the central facade for the agent module. It:
    1. Wires up the AutoTradingPipeline (market → selector → trader loop).
    2. Provides a high-level API for web routes and external triggers.
    3. Delegates TTS/voice commentary through the existing TTSService.
"""

from __future__ import annotations

import logging
from typing import Any, TypeAlias

from stockstream.agent.strategy.pipeline import AutoTradingPipeline
from stockstream.agent.trader.service import TraderAgentService
from stockstream.core.config import get_settings
from stockstream.selector.service import SelectorService
from stockstream.tts.service import TTSService

logger = logging.getLogger(__name__)

JSON: TypeAlias = dict[str, Any]  # noqa: N816  # pyright: ignore[reportExplicitAny]


class AgentService:
    """Central trading agent — owns the pipeline and exposes a clean API.

    Usage::

        agent = AgentService(
            selector=selector,
            tts=tts,
            trader=trader,
            market_storage=market_storage,
        )
        await agent.start_auto_trading()
        report = agent.status()
        await agent.stop_auto_trading()
    """

    selector: SelectorService
    tts: TTSService
    trader: TraderAgentService
    _pipeline: AutoTradingPipeline

    def __init__(
        self,
        selector: SelectorService,
        tts: TTSService,
        trader: TraderAgentService,
        market_storage: Any,  # pyright: ignore[reportExplicitAny, reportAny]
    ) -> None:
        self.selector = selector
        self.tts = tts
        self.trader = trader

        settings = get_settings()
        self._pipeline = AutoTradingPipeline(
            market_storage=market_storage,
            selector=selector,
            trader=trader,
            tick_seconds=getattr(settings, "trader_tick_seconds", 10.0),
            auto_open=getattr(settings, "trader_auto_open", True),
            auto_add=getattr(settings, "trader_auto_add", True),
            auto_reduce=getattr(settings, "trader_auto_reduce", False),
            auto_clear=getattr(settings, "trader_auto_clear", True),
            report_dir=getattr(settings, "trader_report_dir", None) or None,
        )

    # ── auto-trading lifecycle ────────────────────────────────────

    @property
    def auto_trading(self) -> bool:
        """Whether the background auto-trading loop is running."""
        return self._pipeline.running

    async def start_auto_trading(self) -> JSON:
        """Start the background auto-trading loop.

        Returns a status dict. Idempotent — safe to call multiple times.
        """
        if self._pipeline.running:
            return {"status": "already_running", "tick_count": self._pipeline.tick_count}
        await self._pipeline.start()
        logger.info("Auto-trading started")
        return {"status": "started", "tick_count": 0}

    async def stop_auto_trading(self) -> JSON:
        """Stop the background auto-trading loop gracefully."""
        count = self._pipeline.tick_count
        await self._pipeline.stop()
        logger.info("Auto-trading stopped at tick %d", count)
        return {"status": "stopped", "tick_count": count}

    async def tick_once(self) -> JSON:
        """Run a single manual pipeline tick (for testing / dry-run).

        Uses the public _tick method which goes through the full decision cycle.
        """
        report = await self._pipeline._tick()  # pyright: ignore[reportPrivateUsage]
        return report.to_dict()

    def status(self) -> JSON:
        """Return live pipeline + portfolio status."""
        report = self._pipeline.last_report
        return {
            "auto_trading": self._pipeline.running,
            "tick_count": self._pipeline.tick_count,
            "tick_seconds": self._pipeline._tick_seconds,  # pyright: ignore[reportPrivateUsage]
            "phase": self._pipeline.phase,
            "last_report": report.to_dict() if report else None,
            "portfolio": self.trader.get_portfolio_dict(),
            "auto_open": self._pipeline._auto_open,  # pyright: ignore[reportPrivateUsage]
            "auto_add": self._pipeline._auto_add,  # pyright: ignore[reportPrivateUsage]
            "auto_reduce": self._pipeline._auto_reduce,  # pyright: ignore[reportPrivateUsage]
            "auto_clear": self._pipeline._auto_clear,  # pyright: ignore[reportPrivateUsage]
        }

    # ── manual trading shortcuts (delegate to trader) ──────────────

    def open_position(
        self, symbol: str, name: str, price: float, shares: int,
    ) -> JSON:
        return self.trader.open(symbol=symbol, name=name, price=price, shares=shares)

    def add_position(self, symbol: str, price: float, shares: int) -> JSON:
        return self.trader.add(symbol=symbol, price=price, shares=shares)

    def close_position(self, symbol: str, price: float) -> JSON:
        return self.trader.close(symbol=symbol, price=price)

    # ── voice / TTS (existing API preserved) ───────────────────────

    async def brief(self, symbols: list[str]) -> JSON:
        """Generate a compact market brief for ranked symbols."""
        rankings = await self.selector.rank(symbols)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
        # rankings iter yields dict[Unknown, Unknown], joined items go into str()
        message = "关注: " + ", ".join(
            str(item["symbol"]) for item in rankings[:3]  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]
        )
        task = await self.tts.speak(message)
        return {
            "rankings": rankings,
            "task_id": task.task_id,
            "status": task.task_id,
        }

    async def speak_commentary(self, text: str) -> JSON:
        """Shortcut: synthesise a pre-written commentary script."""
        task = await self.tts.speak(text)
        return task.to_dict()
