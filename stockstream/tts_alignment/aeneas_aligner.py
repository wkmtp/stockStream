"""aeneas forced-alignment backend.

Uses the aeneas library (with espeak-ng) to perform true forced alignment
between a synthesised WAV file and the original narration text.

Pipeline::

    text ──► split into per-word TextFragments
                │
    wav ────► aeneas.ExecuteTask ──► sync_map (word-level timestamps)
                │
                ▼
    AlignmentResult with per-word start_sec

If aeneas is not installed, this module gracefully degrades and
reports ``available=False``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from stockstream.tts_alignment.models import AlignmentWord, AlignmentResult, AlignmentMethod

logger = logging.getLogger(__name__)

# ── aeneas import ──────────────────────────────────────────────────────
_AENEAS_AVAILABLE = False
_AENEAS_ERROR = ""

try:
    import aeneas.executetask  # noqa: F401
    import aeneas.task  # noqa: F401
    import aeneas.textfile  # noqa: F401
    import aeneas.language  # noqa: F401
    import aeneas.syncmap  # noqa: F401
    import aeneas.runtimeconfiguration  # noqa: F401
    _AENEAS_AVAILABLE = True
except ImportError as exc:
    _AENEAS_ERROR = str(exc)
    logger.info(
        "aeneas not available — install with: pip install aeneas  "
        "(requires espeak-ng system package). Error: %s", _AENEAS_ERROR,
    )

# Language code for Mandarin Chinese in aeneas
_LANG_CMN = "cmn"


class AeneasAligner:
    """Forced-alignment engine using aeneas + espeak-ng.

    Works by:
      1. Splitting the text into per-character text fragments
      2. Using espeak-ng to synthesise expected phonemes
      3. Aligning the expected phoneme sequence against actual audio via DTW
      4. Extracting per-word start/end times from the sync map

    Chinese-specific notes:
      - Language code: "cmn" (Mandarin Chinese)
      - Each Chinese character is treated as a separate word fragment
      - espeak-ng must have the Chinese voice data installed
    """

    def __init__(self) -> None:
        self._available = _AENEAS_AVAILABLE

    @property
    def available(self) -> bool:
        return self._available

    def align(
        self,
        text: str,
        wav_path: str,
        *,
        language: str = _LANG_CMN,
    ) -> AlignmentResult:
        """Run forced alignment on a text + WAV pair.

        Args:
            text: The original narration text (e.g. "贵州茅台今日...")
            wav_path: Path to the synthesised WAV file.
            language: ISO 639-3 language code (default: "cmn").

        Returns:
            AlignmentResult with per-word timestamps.
        """
        if not self._available:
            return AlignmentResult(
                text=text,
                wav_path=wav_path,
                method=AlignmentMethod.AENEAS,
                error=f"aeneas not installed: {_AENEAS_ERROR}",
            )

        if not text or not text.strip():
            return AlignmentResult(
                text=text,
                wav_path=wav_path,
                method=AlignmentMethod.AENEAS,
                error="empty text",
            )

        if not os.path.isfile(wav_path):
            return AlignmentResult(
                text=text,
                wav_path=wav_path,
                method=AlignmentMethod.AENEAS,
                error=f"WAV file not found: {wav_path}",
            )

        return self._do_align(text, wav_path, language)

    def _do_align(
        self,
        text: str,
        wav_path: str,
        language: str,
    ) -> AlignmentResult:
        """Core aeneas alignment implementation."""
        try:
            from aeneas.executetask import ExecuteTask
            from aeneas.task import Task
            from aeneas.textfile import TextFile, TextFragment
            from aeneas.language import Language
            from aeneas.syncmap import SyncMapFragment, SyncMapFormat
            from aeneas.runtimeconfiguration import RuntimeConfiguration

            text = text.strip()

            # ── Build per-character text fragments ─────────────────
            # Each Chinese character = one fragment for word-level alignment
            textfile = TextFile()
            for i, ch in enumerate(text):
                if ch.strip():  # skip whitespace-only chars
                    identifier = f"f{i:04d}"
                    fragment = TextFragment(
                        identifier,
                        Language.CMN,
                        [ch],      # text_lines — the actual text
                        [ch],      # filtered_lines — same for clean text
                    )
                    textfile.add_fragment(fragment)

            if len(textfile) == 0:
                return AlignmentResult(
                    text=text,
                    wav_path=wav_path,
                    method=AlignmentMethod.AENEAS,
                    error="no valid text fragments",
                )

            # ── Create task ────────────────────────────────────────
            config_string = (
                f"task_language={language}|"
                "is_text_type=unparsed|"
                "os_task_file_format=json"
            )
            task = Task(config_string=config_string)
            task.audio_file_path_absolute = os.path.abspath(wav_path)
            task.text_file = textfile

            # ── Runtime configuration for finer alignment ──────────
            # Smaller MFCC window shift = finer time granularity for short segments
            rconf = RuntimeConfiguration()
            # For short Chinese sentences, use smaller windows
            rconf["mfcc_window_length"] = "0.025"   # 25ms (default)
            rconf["mfcc_window_shift"] = "0.010"     # 10ms (default)

            # ── Execute alignment ──────────────────────────────────
            logger.debug(
                "aeneas aligning: %d chars, wav=%s",
                len(text), Path(wav_path).name,
            )
            executor = ExecuteTask(task, rconf=rconf)
            executor.execute()

            # ── Extract sync map leaves ────────────────────────────
            sync_leaves: list[SyncMapFragment] = task.sync_map_leaves()

            # ── Build word list from sync map ──────────────────────
            words: list[AlignmentWord] = []
            timestamps: dict[str, float] = {}

            for leaf in sync_leaves:
                begin = leaf.begin
                end = leaf.end
                # leaf.text is the fragment text; for per-char alignment
                # each leaf should correspond to one character
                leaf_text = leaf.text

                if begin is None or end is None:
                    continue

                # Handle multi-line fragments (aeneas may group)
                lines = leaf.lines if hasattr(leaf, 'lines') else [leaf_text]
                for line in lines:
                    if not line:
                        continue
                    word = AlignmentWord(
                        text=line,
                        start_sec=begin,
                        end_sec=end,
                    )
                    words.append(word)
                    timestamps[line] = begin

            # ── Compute char_timestamps ────────────────────────────
            char_timestamps: dict[str, float] = {}
            if len(words) == len(text):
                # Per-character alignment: direct mapping
                for i, w in enumerate(words):
                    char_timestamps[w.text] = w.start_sec
            else:
                # Mismatch: redistribute by index proportionally
                char_timestamps = _redistribute_to_chars(words, text)

            total_dur = words[-1].end_sec if words else 0.0

            logger.info(
                "aeneas alignment done: %d words, %.2fs total",
                len(words), total_dur,
            )

            return AlignmentResult(
                text=text,
                wav_path=wav_path,
                method=AlignmentMethod.AENEAS,
                words=words,
                total_duration_sec=total_dur,
                timestamps=timestamps,
                char_timestamps=char_timestamps,
                confidence=0.85,  # aeneas DTW typically good
            )

        except Exception as exc:
            logger.warning("aeneas alignment failed: %s", exc, exc_info=True)
            return AlignmentResult(
                text=text,
                wav_path=wav_path,
                method=AlignmentMethod.AENEAS,
                error=f"aeneas execution error: {exc}",
            )


def _redistribute_to_chars(
    words: list[AlignmentWord],
    text: str,
) -> dict[str, float]:
    """Redistribute word-level timestamps to per-character when counts mismatch.

    When aeneas returns fewer/more fragments than characters, this distributes
    timing proportionally across the character string.
    """
    result: dict[str, float] = {}
    if not words or not text:
        return result

    total_words = len(words)
    total_chars = len(text)
    chars_per_word = max(1, total_chars / max(1, total_words))

    for wi, word in enumerate(words):
        # Map this word to a range of characters
        char_start = int(wi * chars_per_word)
        char_end = int((wi + 1) * chars_per_word)
        char_end = min(char_end, total_chars)

        word_chars = text[char_start:char_end]
        if not word_chars:
            continue

        word_dur = word.duration_sec
        per_char_dur = word_dur / len(word_chars)

        for ci, ch in enumerate(word_chars):
            start = word.start_sec + ci * per_char_dur
            result[ch] = start

    return result
