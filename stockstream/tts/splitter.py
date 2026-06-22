"""Sentence splitter for live-streaming TTS playback.

Splits long Chinese financial commentary into short, speakable sentences
suitable for real-time Piper synthesis. Each sentence is kept short (≤50
chars) to minimise latency between writing and hearing.
"""

from __future__ import annotations

import re
import logging

from stockstream.tts.models import Sentence

logger = logging.getLogger(__name__)

# Sentence-ending punctuation (Chinese + Western)
_SENTENCE_END = re.compile(r"[。！？；!?;\n]+")

# Secondary split points for very long fragments
_SECONDARY_SPLIT = re.compile(r"[，,：:]+")

# Max characters per sentence — tuned for live TTS latency
_MAX_CHARS = 50
_MIN_CHARS = 4


def split_sentences(text: str, max_chars: int = _MAX_CHARS) -> list[Sentence]:
    """Split a multi-sentence text into short speakable fragments.

    Strategy:
        1. Split on strong punctuation (。！？；)
        2. For fragments exceeding *max_chars*, split further on commas
        3. Merge very short fragments into neighbours when possible
        4. Strip whitespace and skip empty fragments

    Args:
        text: Raw commentary text (may contain newlines and extra spaces).
        max_chars: Maximum characters per sentence (default 50).

    Returns:
        Ordered list of Sentence objects ready for synthesis.
    """
    if not text or not text.strip():
        return []

    cleaned = _pre_clean(text)
    fragments = _primary_split(cleaned)
    fragments = _secondary_split(fragments, max_chars)
    fragments = _merge_short(fragments)
    fragments = _trim(fragments)

    results: list[Sentence] = []
    for idx, fragment in enumerate(fragments):
        if len(fragment) >= _MIN_CHARS:
            results.append(Sentence(index=idx, text=fragment))

    if not results and cleaned.strip():
        results.append(Sentence(index=0, text=cleaned.strip()[:max_chars]))

    logger.debug("Split %d chars into %d sentences", len(text), len(results))
    return results


# ── internal helpers ──────────────────────────────────────────────────


def _pre_clean(text: str) -> str:
    """Normalise whitespace and remove markdown artifacts."""
    # Collapse newlines & multiple spaces
    text = re.sub(r"\s+", "", text)
    # Remove common AI artifacts
    text = text.replace("**", "").replace("---", "").replace("```", "")
    # Remove markdown-style quotes
    text = text.replace(">", "")
    return text


def _primary_split(text: str) -> list[str]:
    """Split on strong sentence-ending punctuation, preserving the delimiter."""
    parts = _SENTENCE_END.split(text)
    return [p for p in parts if p]


def _secondary_split(fragments: list[str], max_chars: int) -> list[str]:
    """Split any fragment exceeding max_chars on secondary punctuation."""
    result: list[str] = []
    for frag in fragments:
        if len(frag) <= max_chars:
            result.append(frag)
        else:
            sub_parts = _SECONDARY_SPLIT.split(frag)
            sub_parts = [s for s in sub_parts if s]
            for sp in sub_parts:
                if len(sp) > max_chars:
                    # Hard break at max_chars boundary
                    for i in range(0, len(sp), max_chars):
                        result.append(sp[i : i + max_chars])
                else:
                    result.append(sp)
    return result


def _merge_short(fragments: list[str]) -> list[str]:
    """Merge only genuinely short fragments (< _MIN_CHARS) into neighbours."""
    if not fragments:
        return []
    merged: list[str] = []
    buffer = ""
    for frag in fragments:
        # Only merge if current fragment is too short to be speakable
        if len(frag) < _MIN_CHARS:
            candidate = buffer + frag if buffer else frag
            if len(candidate) <= _MAX_CHARS:
                buffer = candidate
                continue
            # candidate too long — flush buffer, keep current
            if buffer:
                merged.append(buffer)
            buffer = frag
        else:
            # Fragment is already speakable — flush if buffer has pending merges
            if buffer:
                merged.append(buffer)
                buffer = ""
            merged.append(frag)
    if buffer:
        merged.append(buffer)
    return merged


def _trim(fragments: list[str]) -> list[str]:
    """Strip and drop empty/near-empty fragments."""
    return [f.strip() for f in fragments if f.strip()]
