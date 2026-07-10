"""Portfolio persistence via a single JSON file.

Concurrency note: writes use atomic rename (write-tmp → rename) on POSIX;
on Windows the file is written synchronously via json.dump.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from stockstream.agent.trader.models import Portfolio

logger = logging.getLogger(__name__)


_DEFAULT_PATH = os.path.join("data", "portfolio.json")


class PortfolioRepository:
    """Read/write Portfolio to/from portfolio.json."""

    def __init__(self, file_path: str | None = None) -> None:
        self.file_path = file_path or _DEFAULT_PATH

    # ── load ──────────────────────────────────────────────────────

    def load(self) -> Portfolio:
        """Load portfolio from disk. Returns a fresh default if file missing."""
        if not os.path.exists(self.file_path):
            return Portfolio(cash=3000.0, initial_capital=3000.0)
        try:
            with open(self.file_path, "r", encoding="utf-8") as file:
                data = json.load(file)
            return Portfolio.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("Failed to parse portfolio.json, starting fresh: %s", exc)
            return Portfolio(cash=3000.0, initial_capital=3000.0)

    # ── save ──────────────────────────────────────────────────────

    def save(self, portfolio: Portfolio) -> None:
        """Persist portfolio atomically (best-effort atomic on Windows)."""
        Path(self.file_path).parent.mkdir(parents=True, exist_ok=True)
        data = portfolio.to_dict()
        try:
            # POSIX atomic: write-to-tmp + os.replace
            fd, tmp_path = tempfile.mkstemp(
                dir=os.path.dirname(self.file_path) or ".",
                prefix=".portfolio_",
                suffix=".tmp",
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
                    json.dump(data, tmp_file, ensure_ascii=False, indent=2)
                os.replace(tmp_path, self.file_path)
            except Exception:
                os.unlink(tmp_path)
                raise
        except OSError:
            # Fallback: direct write
            with open(self.file_path, "w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
        logger.debug("Portfolio saved to %s (cash=%.2f)", self.file_path, portfolio.cash)
