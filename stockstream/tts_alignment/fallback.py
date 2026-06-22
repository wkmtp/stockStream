"""Fallback alignment strategies when aeneas is unavailable.

Two fallback tiers:
  1. WAV-proportional: read actual WAV duration, distribute timing
     proportionally by character weight (CJK=1.0, digit=0.7, punct=0.3)
  2. Pure char-count: fixed speaking rate (4.5 chars/sec) with
     character weight distribution
"""

from __future__ import annotations

import logging
import os
import struct

from stockstream.tts_alignment.models import AlignmentWord, AlignmentResult, AlignmentMethod

logger = logging.getLogger(__name__)

_DEFAULT_CHARS_PER_SEC = 4.5
_DEFAULT_MS_PER_WEIGHT = 1000.0 / _DEFAULT_CHARS_PER_SEC  # ~222ms per char


def _char_weight(ch: str) -> float:
    """Speaking-time weight for a single character.

    CJK chars = 1.0, digits/ASCII = 0.7, punctuation = 0.3.
    """
    code = ord(ch)
    if 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF:
        return 1.0
    if 0xFF00 <= code <= 0xFFEF:
        return 0.4
    if ch.isdigit():
        return 0.7
    if ch.isascii() and ch.isalpha():
        return 0.7
    if ch in "。，、；：！？…—""''（）《》【】":
        return 0.3
    return 1.0


def _estimate_char_words(text: str, chars_per_sec: float) -> list[AlignmentWord]:
    """Build per-character AlignmentWord list from pure char-count estimation."""
    words: list[AlignmentWord] = []
    current_sec = 0.0
    ms_per_weight = 1.0 / chars_per_sec

    for ch in text:
        weight = _char_weight(ch)
        dur = max(0.02, weight * ms_per_weight)
        words.append(AlignmentWord(
            text=ch,
            start_sec=round(current_sec, 4),
            end_sec=round(current_sec + dur, 4),
        ))
        current_sec += dur

    return words


def _read_wav_duration_sec(wav_path: str) -> float | None:
    """Read WAV file header and return duration in seconds.

    Returns None if the file cannot be read or parsed.
    """
    if not os.path.isfile(wav_path):
        return None

    try:
        with open(wav_path, "rb") as f:
            if f.read(4) != b"RIFF":
                return None
            _ = f.read(4)
            if f.read(4) != b"WAVE":
                return None

            sample_rate = 22050
            data_size = 0
            found_data = False

            while True:
                chunk_id = f.read(4)
                if len(chunk_id) < 4:
                    break
                chunk_size = struct.unpack("<I", f.read(4))[0]
                if chunk_id == b"fmt ":
                    fmt_data = f.read(chunk_size)
                    sample_rate = struct.unpack("<I", fmt_data[4:8])[0]
                elif chunk_id == b"data":
                    data_size = chunk_size
                    found_data = True
                    break
                else:
                    f.seek(chunk_size, 1)

            if not found_data or data_size <= 0:
                return None

            # 16-bit mono: bytes_per_sample=2, channels=1
            bytes_per_sec = sample_rate * 2
            return data_size / bytes_per_sec

    except Exception as exc:
        logger.warning("Failed to read WAV duration: %s", exc)
        return None


def align_wav_proportional(
    text: str,
    wav_path: str,
    chars_per_sec: float = _DEFAULT_CHARS_PER_SEC,
) -> AlignmentResult:
    """Align using WAV duration + proportional character-weight distribution.

    This is more accurate than pure char-count because it respects the
    actual audio duration. It distributes timing proportionally across
    characters based on their weight.

    Returns:
        AlignmentResult with method=WAV_PROPORTIONAL or CHAR_COUNT.
    """
    text = text.strip()
    if not text:
        return AlignmentResult(
            text=text, wav_path=wav_path,
            method=AlignmentMethod.CHAR_COUNT,
            error="empty text",
        )

    # Read actual WAV duration
    actual_dur = _read_wav_duration_sec(wav_path)

    if actual_dur is not None and actual_dur > 0:
        # ── WAV-proportional mode ─────────────────────────────────
        # Estimate base timing by char weight
        base_words = _estimate_char_words(text, chars_per_sec)
        if not base_words:
            return AlignmentResult(
                text=text, wav_path=wav_path,
                method=AlignmentMethod.WAV_PROPORTIONAL,
                error="no words estimated",
            )

        estimated_dur = base_words[-1].end_sec
        if estimated_dur <= 0:
            return AlignmentResult(
                text=text, wav_path=wav_path,
                method=AlignmentMethod.WAV_PROPORTIONAL,
                error="zero estimated duration",
            )

        scale = actual_dur / estimated_dur

        words = [
            AlignmentWord(
                text=w.text,
                start_sec=round(w.start_sec * scale, 4),
                end_sec=round(w.end_sec * scale, 4),
            )
            for w in base_words
        ]

        timestamps = {w.text: w.start_sec for w in words}
        char_timestamps = dict(timestamps)

        logger.debug(
            "WAV-proportional: %.2fs actual, %d chars, scale=%.3f",
            actual_dur, len(words), scale,
        )

        return AlignmentResult(
            text=text,
            wav_path=wav_path,
            method=AlignmentMethod.WAV_PROPORTIONAL,
            words=words,
            total_duration_sec=round(actual_dur, 4),
            timestamps=timestamps,
            char_timestamps=char_timestamps,
            confidence=0.5,
        )

    else:
        # ── Pure char-count fallback ──────────────────────────────
        words = _estimate_char_words(text, chars_per_sec)
        if not words:
            return AlignmentResult(
                text=text, wav_path=wav_path,
                method=AlignmentMethod.CHAR_COUNT,
                error="no words estimated",
            )

        total_dur = words[-1].end_sec
        timestamps = {w.text: w.start_sec for w in words}
        char_timestamps = dict(timestamps)

        logger.debug(
            "Char-count fallback: %.2fs, %d chars",
            total_dur, len(words),
        )

        return AlignmentResult(
            text=text,
            wav_path=wav_path,
            method=AlignmentMethod.CHAR_COUNT,
            words=words,
            total_duration_sec=round(total_dur, 4),
            timestamps=timestamps,
            char_timestamps=char_timestamps,
            confidence=0.3,
        )
