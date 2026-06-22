"""Word-level timing estimator for Chinese narration text.

Since Piper TTS does not expose phoneme-level timestamps, we estimate per-word
timing based on character count and an empirically-tuned speaking rate.

Key parameters:
  - chars_per_second: average Chinese speaking rate (financial broadcast pace)
  - word_group_size:  how many chars to group into one SRT entry line
  - entry_overlap_ms: small overlap between consecutive SRT entries for readability
"""

from __future__ import annotations

import logging

from stockstream.subtitle_engine.models import SubtitleWord, SrtEntry

logger = logging.getLogger(__name__)

# ── timing defaults ─────────────────────────────────────────────────────
# Financial broadcast / 财经播报 — slightly faster than conversational speech
_DEFAULT_CHARS_PER_SEC = 4.5        # ~4.5 chars/sec for clear financial narration
_DEFAULT_WORD_GROUP_SIZE = 6        # ~6 chars per SRT line (readable on screen)
_DEFAULT_ENTRY_OVERLAP_MS = 150     # 150ms overlap between consecutive entries

# Per-character timing bias: CJK chars take ~1x, digits/English ~0.7x, punctuation ~0.3x
_CHAR_WEIGHT_MAP: dict[str, float] = {}

def _char_weight(ch: str) -> float:
    """Return speaking-time weight for a single character."""
    code = ord(ch)
    # CJK Unified Ideographs block
    if 0x4E00 <= code <= 0x9FFF:
        return 1.0
    # CJK Extension A
    if 0x3400 <= code <= 0x4DBF:
        return 1.0
    # Full-width punctuation / symbols
    if 0xFF00 <= code <= 0xFFEF:
        return 0.4
    # Digits 0-9
    if ch.isdigit():
        return 0.7
    # ASCII letters
    if ch.isascii() and ch.isalpha():
        return 0.7
    # Punctuation / spaces
    if ch in "。，、；：！？…—""''（）《》【】":
        return 0.3
    # Default
    return 1.0


def estimate_timing(
    text: str,
    chars_per_sec: float = _DEFAULT_CHARS_PER_SEC,
    word_group_size: int = _DEFAULT_WORD_GROUP_SIZE,
    entry_overlap_ms: int = _DEFAULT_ENTRY_OVERLAP_MS,
) -> tuple[list[SubtitleWord], list[SrtEntry], int]:
    """Estimate per-word and per-entry timings for a narration text.

    Args:
        text: Full narration text (e.g. "贵州茅台今日主力资金净流入2.1亿")
        chars_per_sec: Speaking rate in characters per second.
        word_group_size: How many words/chars per SRT entry line.
        entry_overlap_ms: Overlap in ms between consecutive SRT entries.

    Returns:
        (words, entries, total_duration_ms)
        - words: per-character SubtitleWord list with absolute timestamps
        - entries: SRT entry list (grouped words) with absolute timestamps
        - total_duration_ms: total estimated duration in ms
    """
    if not text or not text.strip():
        return [], [], 0

    text = text.strip()

    # ── Step 1: per-word timing ────────────────────────────────────
    words: list[SubtitleWord] = []
    current_ms = 0
    ms_per_weight_unit = 1000.0 / chars_per_sec

    for i, ch in enumerate(text):
        weight = _char_weight(ch)
        duration_ms = max(20, int(weight * ms_per_weight_unit))  # minimum 20ms per char
        words.append(SubtitleWord(
            text=ch,
            start_ms=current_ms,
            end_ms=current_ms + duration_ms,
        ))
        current_ms += duration_ms

    total_duration_ms = current_ms

    # ── Step 2: group words into SRT entries ───────────────────────
    entries: list[SrtEntry] = []
    entry_idx = 1

    # Group words by word_group_size
    for i in range(0, len(words), word_group_size):
        group = words[i:i + word_group_size]
        if not group:
            break

        start_ms = group[0].start_ms
        end_ms = group[-1].end_ms

        # Add overlap: extend end slightly into next group, and start slightly before
        if i > 0:
            start_ms = max(0, start_ms - entry_overlap_ms)
        if i + word_group_size < len(words):
            end_ms = min(total_duration_ms, end_ms + entry_overlap_ms)

        group_text = "".join(w.text for w in group)

        entries.append(SrtEntry(
            index=entry_idx,
            start_ms=start_ms,
            end_ms=end_ms,
            text=group_text,
        ))
        entry_idx += 1

    logger.debug(
        "Timing estimated for %d chars: %d words, %d entries, %dms total (%.1f chars/sec)",
        len(text), len(words), len(entries), total_duration_ms, chars_per_sec,
    )

    return words, entries, total_duration_ms


def estimate_words_from_wav(
    text: str,
    wav_path: str,
) -> tuple[list[SubtitleWord], list[SrtEntry], int] | None:
    """Estimate per-word timing using actual WAV duration (when available).

    This reads the WAV header to get actual audio duration and distributes
    word timing proportionally. More accurate than pure char-count estimation.

    Args:
        text: Narration text corresponding to the WAV.
        wav_path: Path to the synthesised WAV file.

    Returns:
        Same as estimate_timing(), or None if WAV cannot be read.
    """
    import struct
    import os

    if not os.path.isfile(wav_path):
        logger.warning("WAV not found for timing: %s", wav_path)
        return None

    try:
        with open(wav_path, "rb") as f:
            # Read WAV header
            riff = f.read(4)
            if riff != b"RIFF":
                return None
            _ = f.read(4)  # file size
            wave = f.read(4)
            if wave != b"WAVE":
                return None

            # Find fmt chunk
            while True:
                chunk_id = f.read(4)
                chunk_size = struct.unpack("<I", f.read(4))[0]
                if chunk_id == b"fmt ":
                    fmt_data = f.read(chunk_size)
                    sample_rate = struct.unpack("<I", fmt_data[4:8])[0]
                    # byte_rate = struct.unpack("<I", fmt_data[8:12])[0]
                elif chunk_id == b"data":
                    data_size = chunk_size
                    break
                else:
                    f.seek(chunk_size, 1)

            # Calculate duration: data_size bytes / (sample_rate * channels * bytes_per_sample)
            # For 16-bit mono: bytes_per_sample = 2, channels = 1
            bytes_per_sec = sample_rate * 2  # 16-bit mono
            actual_duration_ms = int(data_size / bytes_per_sec * 1000)

            # Use char-weight proportional distribution with actual total duration
            words, _, _ = estimate_timing(text)
            if not words:
                return None

            # Re-scale: distribute actual duration proportionally
            estimated_total = words[-1].end_ms if words else 0
            if estimated_total <= 0:
                return None

            scale = actual_duration_ms / estimated_total

            rescaled_words: list[SubtitleWord] = []
            for w in words:
                rescaled_words.append(SubtitleWord(
                    text=w.text,
                    start_ms=int(w.start_ms * scale),
                    end_ms=int(w.end_ms * scale),
                ))

            # Rebuild entries from rescaled words
            entries = _build_entries_from_words(rescaled_words)
            total_ms = int(actual_duration_ms)

            logger.debug(
                "WAV-based timing: %.1fs actual → %d words, %d entries",
                actual_duration_ms / 1000, len(rescaled_words), len(entries),
            )
            return rescaled_words, entries, total_ms

    except Exception as exc:
        logger.warning("Failed to read WAV timing: %s", exc)
        return None


def _build_entries_from_words(
    words: list[SubtitleWord],
    group_size: int = _DEFAULT_WORD_GROUP_SIZE,
    overlap_ms: int = _DEFAULT_ENTRY_OVERLAP_MS,
) -> list[SrtEntry]:
    """Rebuild SRT entries from a word list (used after WAV rescaling)."""
    entries: list[SrtEntry] = []
    entry_idx = 1
    total = len(words)

    for i in range(0, total, group_size):
        group = words[i:i + group_size]
        if not group:
            break
        start_ms = group[0].start_ms
        end_ms = group[-1].end_ms
        if i > 0:
            start_ms = max(0, start_ms - overlap_ms)
        if i + group_size < total:
            end_ms = min(words[-1].end_ms if words else 0, end_ms + overlap_ms)
        group_text = "".join(w.text for w in group)
        entries.append(SrtEntry(index=entry_idx, start_ms=start_ms, end_ms=end_ms, text=group_text))
        entry_idx += 1

    return entries
