"""Alignment engine — unified forced-alignment with automatic backend selection.

The AlignmentEngine receives Piper TTS audio + original text and produces
per-word/character timestamps for subtitle synchronisation.

Backend priority::

    1. aeneas (forced alignment via espeak-ng synthesis + DTW)
    2. WAV-proportional (actual WAV duration + char-weight distribution)
    3. Char-count estimation (fixed speaking rate, last resort)

Usage::

    engine = AlignmentEngine()
    await engine.start()

    result = await engine.align(
        text="贵州茅台今日主力资金净流入2.1亿",
        wav_path="data/tts/xxx.wav",
    )
    # result.timestamps → {"贵": 0.0, "州": 0.12, "茅": 0.24, ...}
    # result.words → [AlignmentWord("贵", 0.0, 0.12), ...]

Integration with subtitle_engine::

    from stockstream.tts_alignment import create_alignment_engine

    aligner = create_alignment_engine()
    result = await aligner.align(text, wav_path)

    # Convert to SubtitleWord for subtitle_engine compatibility:
    from stockstream.subtitle_engine.models import SubtitleWord
    sw = [SubtitleWord(text=w.text, start_ms=w.start_ms, end_ms=w.end_ms)
          for w in result.words]
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Optional

from stockstream.tts_alignment.models import (
    AlignmentResult,
    AlignmentWord,
    AlignmentMethod,
)
from stockstream.tts_alignment.aeneas_aligner import AeneasAligner
from stockstream.tts_alignment.fallback import (
    align_wav_proportional,
)

logger = logging.getLogger(__name__)


class AlignmentEngine:
    """Forced-alignment engine with automatic backend fallback.

    Lifecycle::

        engine = AlignmentEngine()
        await engine.start()

        # Align one text+audio pair
        result = await engine.align("文本", "path/to/audio.wav")

        # Query stats
        stats = engine.stats

        await engine.stop()
    """

    def __init__(
        self,
        *,
        chars_per_sec: float = 4.5,
        max_history: int = 200,
        prefer_aeneas: bool = True,
    ) -> None:
        self.chars_per_sec = chars_per_sec
        self.max_history = max_history
        self.prefer_aeneas = prefer_aeneas

        # Backends
        self._aeneas = AeneasAligner()

        # State
        self._running = False
        self._results: dict[str, AlignmentResult] = {}
        self._latest_id: str | None = None
        self._aeneas_count = 0
        self._wav_count = 0
        self._char_count = 0
        self._fail_count = 0

    @property
    def aeneas_available(self) -> bool:
        return self._aeneas.available

    @property
    def stats(self) -> dict:
        latest = self._results.get(self._latest_id or "") if self._latest_id else None
        return {
            "running": self._running,
            "aeneas_available": self.aeneas_available,
            "aeneas_count": self._aeneas_count,
            "wav_proportional_count": self._wav_count,
            "char_count": self._char_count,
            "fail_count": self._fail_count,
            "total_alignments": len(self._results),
            "latest_id": self._latest_id,
            "latest_text": latest.text[:80] if latest else "",
            "latest_method": latest.method.value if latest else "",
            "chars_per_sec": self.chars_per_sec,
        }

    # ── lifecycle ──────────────────────────────────────────────────

    async def start(self) -> None:
        self._running = True
        logger.info(
            "AlignmentEngine started (aeneas=%s, chars_per_sec=%.1f)",
            self.aeneas_available, self.chars_per_sec,
        )

    async def stop(self) -> None:
        self._running = False
        logger.info("AlignmentEngine stopped (%d results)", len(self._results))

    # ── main API ───────────────────────────────────────────────────

    async def align(
        self,
        text: str,
        wav_path: str = "",
        *,
        align_id: str = "",
    ) -> AlignmentResult:
        """Align text to audio, producing per-word timestamps.

        Args:
            text: Original narration text (Chinese, e.g. "贵州茅台今日...").
            wav_path: Path to the synthesised WAV file.
            align_id: Optional alignment ID (auto-generated if empty).

        Returns:
            AlignmentResult with per-word timestamps, char_timestamps dict,
            and method indicating which backend was used.
        """
        if not align_id:
            align_id = uuid.uuid4().hex[:8]

        text = text.strip()
        if not text:
            result = AlignmentResult(
                text=text, wav_path=wav_path,
                method=AlignmentMethod.CHAR_COUNT,
                error="empty text",
            )
            self._results[align_id] = result
            self._latest_id = align_id
            return result

        result: AlignmentResult | None = None

        # ── Tier 1: aeneas forced alignment ────────────────────────
        if self.prefer_aeneas and self._aeneas.available:
            result = await asyncio.to_thread(
                self._aeneas.align, text, wav_path,
            )
            if result.has_content and not result.error:
                self._aeneas_count += 1
                self._store_result(align_id, result)
                return result
            logger.debug("aeneas alignment unsuccessful, falling back: %s", result.error)

        # ── Tier 2: WAV-proportional distribution ──────────────────
        if wav_path:
            result = await asyncio.to_thread(
                align_wav_proportional, text, wav_path, self.chars_per_sec,
            )
            if result.has_content and not result.error:
                if result.method == AlignmentMethod.WAV_PROPORTIONAL:
                    self._wav_count += 1
                else:
                    self._char_count += 1
                self._store_result(align_id, result)
                return result

        # ── Tier 3: Pure char-count estimation (last resort) ───────
        result = await asyncio.to_thread(
            align_wav_proportional, text, "", self.chars_per_sec,
        )
        self._char_count += 1
        self._store_result(align_id, result)
        return result

    # ── query API ──────────────────────────────────────────────────

    def get_result(self, align_id: str) -> AlignmentResult | None:
        return self._results.get(align_id)

    def get_latest(self) -> AlignmentResult | None:
        if self._latest_id:
            return self._results.get(self._latest_id)
        return None

    def get_timestamps(self, align_id: str) -> dict[str, float]:
        """Return the per-word timestamp dict for an alignment."""
        r = self._results.get(align_id)
        return r.timestamps if r else {}

    def get_char_timestamps(self, align_id: str) -> dict[str, float]:
        """Return the per-character timestamp dict for an alignment."""
        r = self._results.get(align_id)
        return r.char_timestamps if r else {}

    def clear_history(self) -> int:
        count = len(self._results)
        self._results.clear()
        self._latest_id = None
        return count

    # ── internal ───────────────────────────────────────────────────

    def _store_result(self, align_id: str, result: AlignmentResult) -> None:
        self._results[align_id] = result
        self._latest_id = align_id
        self._prune()

    def _prune(self) -> None:
        if len(self._results) <= self.max_history:
            return
        excess = len(self._results) - self.max_history
        keys = list(self._results.keys())[:excess]
        for k in keys:
            del self._results[k]


# ── factory ──────────────────────────────────────────────────────────────

def create_alignment_engine(
    chars_per_sec: float = 4.5,
    max_history: int = 200,
    prefer_aeneas: bool = True,
) -> AlignmentEngine:
    """Create an AlignmentEngine with sensible defaults.

    Args:
        chars_per_sec: Speaking rate for fallback estimation.
        max_history: Maximum number of alignment results to retain.
        prefer_aeneas: Whether to try aeneas first (True) or skip it (False).

    Returns:
        Configured AlignmentEngine instance.
    """
    return AlignmentEngine(
        chars_per_sec=chars_per_sec,
        max_history=max_history,
        prefer_aeneas=prefer_aeneas,
    )
