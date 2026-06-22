"""SRT file writer — generates standard .srt subtitle files.

Outputs standard SRT format compatible with FFmpeg, VLC, and most video players.

Usage::

    writer = SrtWriter(output_dir="cache/subtitle")
    srt_path = writer.write(track)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from datetime import datetime

from stockstream.subtitle_engine.models import SubtitleTrack, SrtEntry

logger = logging.getLogger(__name__)


class SrtWriter:
    """Write SubtitleTrack entries to a standard .srt file."""

    def __init__(self, output_dir: str = "cache/subtitle") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write(self, track: SubtitleTrack, filename: str | None = None) -> str:
        """Write a subtitle track to an SRT file.

        Args:
            track: SubtitleTrack with populated entries.
            filename: Optional custom filename (without extension).
                      Defaults to "subtitle_{task_id}.srt".

        Returns:
            Absolute path to the written SRT file.
        """
        if not track.entries:
            logger.warning("SubtitleTrack %s has no entries, writing empty SRT", track.task_id)
            # Write a minimal valid SRT
            srt_content = "1\n00:00:00,000 --> 00:00:01,000\n \n"
        else:
            srt_content = self._format_srt(track)

        if filename is None:
            filename = f"subtitle_{track.task_id}"

        # Ensure .srt extension
        if not filename.endswith(".srt"):
            filename += ".srt"

        out_path = self.output_dir / filename
        out_path.write_text(srt_content, encoding="utf-8")
        logger.info("SRT written: %s (%d entries, %d bytes)",
                     out_path.name, track.entry_count, len(srt_content))
        return str(out_path.resolve())

    def write_latest(self, track: SubtitleTrack) -> str:
        """Write to a fixed filename 'subtitle.srt' (overwrites, for live streaming)."""
        return self.write(track, filename="subtitle.srt")

    def _format_srt(self, track: SubtitleTrack) -> str:
        """Format all entries as a complete SRT file string."""
        blocks: list[str] = []
        for entry in track.entries:
            blocks.append(entry.to_srt_lines())
        # SRT blocks separated by a blank line, with trailing blank line
        return "\n\n".join(blocks) + "\n"

    def write_segment(
        self,
        track: SubtitleTrack,
        segment_index: int,
        filename: str | None = None,
    ) -> str:
        """Write a single SRT entry as its own file (for per-sentence overlay).

        Args:
            track: SubtitleTrack containing the entries.
            segment_index: 0-based index into track.entries.
            filename: Optional filename override.

        Returns:
            Absolute path to the segment SRT file.
        """
        if segment_index < 0 or segment_index >= len(track.entries):
            raise IndexError(f"segment_index {segment_index} out of range [0, {len(track.entries)})")

        entry = track.entries[segment_index]
        # Re-index as entry #1
        single_entry = SrtEntry(
            index=1,
            start_ms=entry.start_ms,
            end_ms=entry.end_ms,
            text=entry.text,
        )
        srt_content = single_entry.to_srt_lines() + "\n"

        if filename is None:
            filename = f"subtitle_{track.task_id}_seg{segment_index:03d}.srt"

        if not filename.endswith(".srt"):
            filename += ".srt"

        out_path = self.output_dir / filename
        out_path.write_text(srt_content, encoding="utf-8")
        return str(out_path.resolve())

    def list_files(self) -> list[dict]:
        """List all SRT files in the output directory."""
        if not self.output_dir.exists():
            return []
        files = []
        for f in sorted(self.output_dir.glob("*.srt")):
            stat = f.stat()
            files.append({
                "name": f.name,
                "path": str(f.resolve()),
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
        return files

    def clear(self) -> int:
        """Delete all SRT files in the output directory. Returns count deleted."""
        if not self.output_dir.exists():
            return 0
        count = 0
        for f in self.output_dir.glob("*.srt"):
            f.unlink()
            count += 1
        return count
