"""Subtitle engine — real-time SRT + transparent PNG subtitle generation.

Receives digital human narration text and produces:
  - subtitle.srt           — word-synchronised SRT file
  - subtitle_<id>_*.png    — transparent PNG strips for FFmpeg overlay

Lifecycle::

    engine = SubtitleEngine(cache_dir="cache/subtitle")
    await engine.start()

    # When TTS synthesises a sentence:
    track = await engine.receive("贵州茅台今日主力资金净流入2.1亿", wav_path="...")

    # Get outputs:
    srt_path = track.srt_path          # → cache/subtitle/subtitle.srt
    png_paths = engine.get_pngs(track)  # → list of PNG paths

    await engine.stop()

Timing backends (priority):
  1. AlignmentEngine (aeneas forced alignment) — if provided
  2. WAV-proportional distribution (legacy estimate_words_from_wav)
  3. Char-count estimation (legacy estimate_timing)

FFmpeg usage for subtitle overlay::

    ffmpeg -i video.mp4 -vf "subtitles=cache/subtitle/subtitle.srt" output.mp4

FFmpeg usage for PNG overlay (frame sequence)::

    ffmpeg -i video.mp4 -framerate 25 -i cache/subtitle/subtitle_%05d.png \
           -filter_complex "overlay" output.mp4
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from stockstream.subtitle_engine.models import (
    SubtitleTrack,
    SubtitleStyle,
    SubtitleWord,
    SrtEntry,
)
from stockstream.subtitle_engine.timing import estimate_timing, estimate_words_from_wav
from stockstream.subtitle_engine.srt_writer import SrtWriter
from stockstream.subtitle_engine.png_renderer import PngRenderer

if TYPE_CHECKING:
    from stockstream.tts_alignment.engine import AlignmentEngine

logger = logging.getLogger(__name__)


class SubtitleEngine:
    """Real-time subtitle generation engine.

    Features:
    - Per-word timing estimation (aeneas forced alignment > WAV-proportional > char-count)
    - Standard SRT file output (逐字同步)
    - Transparent PNG subtitle layer for FFmpeg overlay
    - Per-sentence track management (each TTS sentence → one track)
    - Frame sequence PNG generation for compositor integration
    """

    def __init__(
        self,
        cache_dir: str = "cache/subtitle",
        style: SubtitleStyle | None = None,
        chars_per_sec: float = 4.5,
        word_group_size: int = 6,
        max_track_history: int = 200,
        alignment_engine: Optional["AlignmentEngine"] = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.style = style or SubtitleStyle()
        self.chars_per_sec = chars_per_sec
        self.word_group_size = word_group_size
        self.max_track_history = max_track_history

        # Alignment engine (optional, for forced alignment)
        self._alignment_engine = alignment_engine

        # Sub-components
        self._srt_writer = SrtWriter(output_dir=str(self.cache_dir))
        self._png_renderer = PngRenderer(output_dir=str(self.cache_dir), style=self.style)

        # State
        self._running = False
        self._tracks: dict[str, SubtitleTrack] = {}      # all tracks by task_id
        self._latest_track_id: str | None = None          # most recent track
        self._collect_count = 0
        self._render_count = 0

    # ── lifecycle ──────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the subtitle engine (currently no background loop needed)."""
        self._running = True
        logger.info("SubtitleEngine started (cache=%s)", self.cache_dir.resolve())

    async def stop(self) -> None:
        """Stop the subtitle engine."""
        self._running = False
        logger.info("SubtitleEngine stopped (tracks=%d)", len(self._tracks))

    # ── main API: receive narration text ───────────────────────────

    async def receive(
        self,
        text: str,
        wav_path: str = "",
        task_id: str = "",
    ) -> SubtitleTrack:
        """Receive a narration sentence and generate subtitle outputs.

        This is the primary entry point. Called by the TTS callback when
        a sentence is synthesised.

        Args:
            text: Narration text (e.g. "贵州茅台今日主力资金净流入2.1亿").
            wav_path: Optional path to the synthesised WAV file for accurate timing.
            task_id: Optional task ID. Auto-generated if not provided.

        Returns:
            SubtitleTrack with populated words, entries, srt_path, and png references.
        """
        if not task_id:
            task_id = uuid.uuid4().hex[:8]

        self._collect_count += 1
        logger.debug("SubtitleEngine received [%s]: %s", task_id, text[:60])

        # ── Step 1: Estimate timing (forced alignment > WAV > char-count) ──
        words: list[SubtitleWord] = []
        entries: list[SrtEntry] = []
        total_ms = 0

        # Tier 1: AlignmentEngine (aeneas forced alignment)
        if self._alignment_engine and wav_path:
            try:
                align_result = await self._alignment_engine.align(
                    text=text, wav_path=wav_path, align_id=task_id,
                )
                if align_result.has_content:
                    words = [
                        SubtitleWord(text=w.text, start_ms=w.start_ms, end_ms=w.end_ms)
                        for w in align_result.words
                    ]
                    total_ms = align_result.total_duration_ms
                    logger.debug(
                        "SubtitleEngine timing via %s: %d words, %dms",
                        align_result.method.value, len(words), total_ms,
                    )
            except Exception as exc:
                logger.debug("AlignmentEngine failed, falling back: %s", exc)

        # Tier 2: WAV-proportional distribution (legacy)
        if not words and wav_path:
            wav_result = await asyncio.to_thread(
                estimate_words_from_wav, text, wav_path,
            )
            if wav_result:
                words, entries, total_ms = wav_result

        # Tier 3: Char-count estimation (last resort)
        if not words:
            words, entries, total_ms = await asyncio.to_thread(
                estimate_timing, text,
                chars_per_sec=self.chars_per_sec,
                word_group_size=self.word_group_size,
            )

        # ── Build SRT entries from words if not already built ──────────
        if words and not entries:
            entries = self._build_entries_from_words(words)

        # ── Step 2: Build track ─────────────────────────────────────
        track = SubtitleTrack(
            task_id=task_id,
            full_text=text,
            words=words,
            entries=entries,
            total_duration_ms=total_ms,
        )

        # ── Step 3: Write SRT files ─────────────────────────────────
        # Write the full track SRT
        track_srt_path = await asyncio.to_thread(
            self._srt_writer.write, track,
        )
        track.srt_path = track_srt_path

        # Also write to the fixed "subtitle.srt" for live compositor
        await asyncio.to_thread(
            self._srt_writer.write_latest, track,
        )

        # ── Step 4: Render PNG entries ──────────────────────────────
        png_paths = await asyncio.to_thread(
            self._png_renderer.render_all_entries, track,
        )
        track.png_dir = str(self.cache_dir.resolve())
        self._render_count += len(png_paths)

        # ── Step 5: Store track ─────────────────────────────────────
        self._tracks[task_id] = track
        self._latest_track_id = task_id
        self._prune_old_tracks()

        logger.info(
            "SubtitleEngine track [%s]: %d chars → %d words, %d entries, %dms, "
            "SRT=%s, PNGs=%d",
            task_id, len(text), len(words), len(entries), total_ms,
            Path(track_srt_path).name if track_srt_path else "none",
            len(png_paths),
        )

        return track

    async def receive_and_render_frames(
        self,
        text: str,
        wav_path: str = "",
        task_id: str = "",
        fps: int = 25,
    ) -> tuple[SubtitleTrack, list[str]]:
        """Receive text AND render full frame sequence PNGs.

        Convenience method that calls receive() + render_frame_sequence().

        Args:
            text: Narration text.
            wav_path: Optional WAV path for timing.
            task_id: Optional task ID.
            fps: Frames per second for PNG sequence.

        Returns:
            (track, png_paths) — the subtitle track and list of frame PNG paths.
        """
        track = await self.receive(text, wav_path=wav_path, task_id=task_id)

        png_paths = await asyncio.to_thread(
            self._png_renderer.render_frame_sequence,
            track, fps=fps, prefix=track.task_id,
        )
        self._render_count += len(png_paths)

        return track, png_paths

    # ── query API ──────────────────────────────────────────────────

    def get_track(self, task_id: str) -> SubtitleTrack | None:
        """Get a subtitle track by task ID."""
        return self._tracks.get(task_id)

    def get_latest_track(self) -> SubtitleTrack | None:
        """Get the most recent subtitle track."""
        if self._latest_track_id:
            return self._tracks.get(self._latest_track_id)
        return None

    def get_latest_srt_path(self) -> str:
        """Get the path to the latest subtitle.srt."""
        p = self.cache_dir / "subtitle.srt"
        return str(p.resolve()) if p.exists() else ""

    def get_pngs(self, track: SubtitleTrack | None = None) -> list[str]:
        """Get PNG file paths for a track, or all PNGs if track is None."""
        if track:
            return [str(p) for p in self.cache_dir.glob(
                f"subtitle_{track.task_id}_entry*.png"
            )]
        return [str(p) for p in sorted(self.cache_dir.glob("*.png"))]

    def get_stats(self) -> dict:
        """Return engine statistics."""
        latest = self.get_latest_track()
        return {
            "running": self._running,
            "cache_dir": str(self.cache_dir.resolve()),
            "collect_count": self._collect_count,
            "render_count": self._render_count,
            "track_count": len(self._tracks),
            "latest_task_id": self._latest_track_id,
            "latest_text": latest.full_text[:100] if latest else "",
            "latest_srt_path": self.get_latest_srt_path(),
            "chars_per_sec": self.chars_per_sec,
            "word_group_size": self.word_group_size,
            "style": self.style.to_dict(),
        }

    async def clear_cache(self) -> int:
        """Clear all SRT and PNG files. Returns count deleted."""
        srt_deleted = await asyncio.to_thread(self._srt_writer.clear)
        png_deleted = await asyncio.to_thread(self._png_renderer.clear_pngs)
        total = srt_deleted + png_deleted
        logger.info("SubtitleEngine cache cleared: %d files", total)
        return total

    async def list_cache(self) -> list[dict]:
        """List all cached subtitle files."""
        srt_files = await asyncio.to_thread(self._srt_writer.list_files)
        png_files = [
            {"name": f.name, "path": str(f.resolve()),
             "size_bytes": f.stat().st_size}
            for f in sorted(self.cache_dir.glob("*.png"))
        ]
        return [{"type": "srt", **f} for f in srt_files] + \
               [{"type": "png", **f} for f in png_files]

    # ── internal ───────────────────────────────────────────────────

    def _prune_old_tracks(self) -> None:
        """Remove oldest tracks when exceeding max history."""
        if len(self._tracks) <= self.max_track_history:
            return
        excess = len(self._tracks) - self.max_track_history
        # Remove oldest (by insertion order)
        keys_to_remove = list(self._tracks.keys())[:excess]
        for key in keys_to_remove:
            del self._tracks[key]

    def _build_entries_from_words(
        self,
        words: list[SubtitleWord],
        group_size: int | None = None,
        overlap_ms: int = 150,
    ) -> list[SrtEntry]:
        """Build SRT entries from a list of per-word timings.

        Groups words into SRT lines of ``group_size`` characters with
        overlap between consecutive entries for readability.
        """
        if group_size is None:
            group_size = self.word_group_size

        entries: list[SrtEntry] = []
        total = len(words)
        entry_idx = 1

        for i in range(0, total, group_size):
            group = words[i:i + group_size]
            if not group:
                break

            start_ms = group[0].start_ms
            end_ms = group[-1].end_ms

            # Add overlap for readability
            if i > 0:
                start_ms = max(0, start_ms - overlap_ms)
            if i + group_size < total:
                end_ms = min(words[-1].end_ms if words else 0, end_ms + overlap_ms)

            group_text = "".join(w.text for w in group)
            entries.append(SrtEntry(
                index=entry_idx,
                start_ms=start_ms,
                end_ms=end_ms,
                text=group_text,
            ))
            entry_idx += 1

        return entries


# ── factory ──────────────────────────────────────────────────────────────

def create_subtitle_engine(
    cache_dir: str = "cache/subtitle",
    chars_per_sec: float = 4.5,
    word_group_size: int = 6,
    width: int = 1920,
    height: int = 80,
    font_size: int = 36,
    alignment_engine: Optional["AlignmentEngine"] = None,
) -> SubtitleEngine:
    """Create a SubtitleEngine with sensible defaults for stock livestream.

    Args:
        cache_dir: Output directory for SRT and PNG files.
        chars_per_sec: Speaking rate (financial broadcast ~4.5 chars/sec).
        word_group_size: Characters per SRT line.
        width: PNG subtitle strip width (match video width).
        height: PNG subtitle strip height.
        font_size: Font size in pixels.
        alignment_engine: Optional AlignmentEngine for forced alignment.

    Returns:
        Configured SubtitleEngine instance.
    """
    style = SubtitleStyle(
        font_size=font_size,
        width=width,
        height=height,
    )
    return SubtitleEngine(
        cache_dir=cache_dir,
        style=style,
        chars_per_sec=chars_per_sec,
        word_group_size=word_group_size,
        alignment_engine=alignment_engine,
    )
