"""Live comment fusion — merge real danmu with simulated audience questions.

Priority: real viewer comments > AI-generated questions. Ensures the show
never feels "empty" while respecting actual audience interaction.
"""

from __future__ import annotations

import asyncio
import logging
import queue
from typing import Any

from stockstream.dual_host.audience_agent import AudienceAgent
from stockstream.dual_host.models import Speaker, DialogTurn, Emotion

logger = logging.getLogger(__name__)


class LiveCommentFusion:
    """Fusion layer that blends real and simulated audience inputs.

    Listens to the stream bus for real danmu events and falls back to
    AI-generated questions when no real viewers are active.
    """

    def __init__(
        self,
        audience_agent: AudienceAgent | None = None,
        *,
        max_recent: int = 50,
        cooldown_sec: float = 15.0,
    ) -> None:
        self.audience = audience_agent or AudienceAgent()
        self._real_queue: queue.Queue[dict] = queue.Queue(maxsize=max_recent)
        self._simulated_queue: queue.Queue[dict] = queue.Queue(maxsize=max_recent)
        self._cooldown_sec = cooldown_sec
        self._last_real_time: float = 0.0
        self._all_questions: list[dict] = []

    # ── input ───────────────────────────────────────────────────

    def push_real(self, username: str, message: str) -> None:
        """Receive a real viewer danmu."""
        import time
        comment = {"username": username, "question": message, "source": "real"}
        try:
            self._real_queue.put_nowait(comment)
            self._last_real_time = time.monotonic()
        except queue.Full:
            pass

    def push_simulated(self, question: dict) -> None:
        """Add an AI-generated question."""
        question["source"] = "simulated"
        try:
            self._simulated_queue.put_nowait(question)
        except queue.Full:
            pass

    # ── output ──────────────────────────────────────────────────

    def get_next(self, watch_list: list[str] | None = None) -> dict | None:
        """Get the next audience question (real preferred, simulated fallback).

        Args:
            watch_list: Current stock symbols for targeted questions.

        Returns:
            Question dict or None if the queue is empty.
        """
        # Check real queue first
        try:
            real = self._real_queue.get_nowait()
            self._all_questions.append(real)
            return real
        except queue.Empty:
            pass

        # Generate new simulated question if needed
        if self._simulated_queue.empty():
            new_q = self.audience.generate_question(watch_list)
            self.push_simulated(new_q)

        try:
            sim = self._simulated_queue.get_nowait()
            self._all_questions.append(sim)
            return sim
        except queue.Empty:
            return None

    def get_batch(self, count: int = 3,
                  watch_list: list[str] | None = None) -> list[dict]:
        """Get multiple questions, real prioritized."""
        results: list[dict] = []
        for _ in range(count):
            q = self.get_next(watch_list)
            if q:
                results.append(q)
        return results

    @property
    def real_ratio(self) -> float:
        """Ratio of real vs total questions in recent history."""
        if not self._all_questions:
            return 0.0
        real_count = sum(1 for q in self._all_questions[-20:] if q.get("source") == "real")
        return real_count / min(20, len(self._all_questions))
