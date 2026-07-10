"""Transparent PNG subtitle layer renderer — for FFmpeg overlay compositing.

Generates per-frame or per-sentence transparent PNG strips with:
  - Semi-transparent background bar
  - Full text with active word highlighted (逐字高亮)
  - Typewriter reveal animation support
  - Per-word frame PNGs for FFmpeg image sequence overlay

Usage::

    renderer = PngRenderer(output_dir="cache/subtitle", style=SubtitleStyle())
    png_path = renderer.render_track_frame(track, progress=0.5)
    # → cache/subtitle/subtitle_abc123_frame_050.png
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from stockstream.subtitle_engine.models import SubtitleTrack, SubtitleStyle, SubtitleWord

logger = logging.getLogger(__name__)

# Font path detection (reuse same logic as video/subtitle_renderer.py)
_FONT_PATH: str | None = None


def _get_font_path() -> str | None:
    """Return path to a Chinese-capable TrueType font."""
    global _FONT_PATH
    if _FONT_PATH is not None:
        return _FONT_PATH or None

    import platform
    import os

    system = platform.system()
    candidates = []

    if system == "Windows":
        windir = os.environ.get("WINDIR", "C:\\Windows")
        candidates = [
            os.path.join(windir, "Fonts", f)
            for f in ["msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc", "msyh.ttf"]
        ]
    elif system == "Darwin":
        candidates = [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
        ]
    else:
        candidates = [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        ]

    for path in candidates:
        if os.path.isfile(path):
            _FONT_PATH = path
            return path

    _FONT_PATH = ""
    return None


class PngRenderer:
    """Render transparent PNG subtitle strips for FFmpeg overlay.

    Features:
    - Semi-transparent rounded background bar
    - Per-character highlight (逐字高亮) for active word
    - Typewriter reveal (逐字显示) animation
    - Transparent background → easy FFmpeg overlay
    """

    def __init__(
        self,
        output_dir: str = "cache/subtitle",
        style: SubtitleStyle | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.style = style or SubtitleStyle()
        self._pil_font = None

    # ── lazy font loading ──────────────────────────────────────────

    def _get_font(self):
        if self._pil_font is None:
            from PIL import ImageFont
            font_path = _get_font_path()
            try:
                if font_path:
                    self._pil_font = ImageFont.truetype(font_path, self.style.font_size)
                else:
                    self._pil_font = ImageFont.load_default()
            except Exception as exc:
                logger.warning("Cannot load font: %s, using default", exc)
                self._pil_font = ImageFont.load_default()
        return self._pil_font

    # ── main rendering API ─────────────────────────────────────────

    def render_full_text(
        self,
        text: str,
        filename: str | None = None,
        highlight_index: int = -1,
    ) -> str:
        """Render a subtitle strip with optional per-character highlight.

        Args:
            text: Full subtitle text.
            filename: Output PNG filename (without extension). Default: auto-generated.
            highlight_index: Index of the character to highlight (-1 = none).

        Returns:
            Absolute path to the rendered PNG file.
        """
        from PIL import Image, ImageDraw

        style = self.style
        width, height = style.width, style.height
        font = self._get_font()

        # Create transparent RGBA canvas
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # ── Background bar ──────────────────────────────────────────
        bg_rgba = (*style.bg_color, int(255 * style.bg_alpha))
        pad = style.padding
        draw.rounded_rectangle(
            [(pad, pad), (width - pad, height - pad)],
            radius=12, fill=bg_rgba,
        )

        # ── Layout characters ───────────────────────────────────────
        chars = list(text)
        if not chars:
            return ""

        # Measure each character's width
        char_widths: list[float] = []
        for ch in chars:
            bbox = draw.textbbox((0, 0), ch, font=font)
            char_widths.append(bbox[2] - bbox[0])

        total_text_w = sum(char_widths)
        # Center text
        start_x = (width - total_text_w) / 2
        # Center vertically
        sample_bbox = draw.textbbox((0, 0), "测", font=font)
        text_h = sample_bbox[3] - sample_bbox[1]
        y = (height - text_h) / 2

        # ── Draw each character ─────────────────────────────────────
        x = start_x
        for i, ch in enumerate(chars):
            # Shadow
            draw.text((x + 2, y + 2), ch, font=font, fill=(0, 0, 0, 140))
            # Main text with optional highlight
            if i == highlight_index and style.highlight_active:
                color = (*style.highlight_color, 255)
            else:
                color = (*style.text_color, 255)
            draw.text((x, y), ch, font=font, fill=color)
            x += char_widths[i]

        # ── Save PNG ────────────────────────────────────────────────
        if filename is None:
            import uuid
            filename = f"subtitle_{uuid.uuid4().hex[:8]}"

        if not filename.endswith(".png"):
            filename += ".png"

        out_path = self.output_dir / filename
        img.save(str(out_path), "PNG")
        return str(out_path.resolve())

    def render_track_frame(
        self,
        track: SubtitleTrack,
        progress: float,
        filename: str | None = None,
    ) -> str:
        """Render a typewriter-reveal subtitle frame for a given progress.

        Args:
            track: SubtitleTrack with word-level timing.
            progress: 0.0 (nothing shown) to 1.0 (fully shown).
            filename: Optional output filename.

        Returns:
            Absolute path to the PNG file.
        """
        total = len(track.words)
        if total == 0:
            return self.render_full_text(track.full_text, filename=filename)

        # Determine how many characters to show and which is active
        shown_count = min(total, max(1, int(total * progress)))
        active_idx = shown_count - 1 if progress < 1.0 else -1

        shown_text = "".join(w.text for w in track.words[:shown_count])

        # Add cursor if still revealing
        if progress < 1.0:
            shown_text += "▎"

        return self.render_full_text(
            shown_text,
            filename=filename,
            highlight_index=active_idx,
        )

    def render_track_frame_by_ms(
        self,
        track: SubtitleTrack,
        elapsed_ms: int,
        filename: str | None = None,
    ) -> str:
        """Render a subtitle frame based on elapsed milliseconds.

        Finds the active word at the given time and highlights it.

        Args:
            track: SubtitleTrack with word timing.
            elapsed_ms: Elapsed time in milliseconds from track start.
            filename: Optional output filename.

        Returns:
            Absolute path to the PNG file.
        """
        total_ms = track.total_duration_ms
        if total_ms <= 0:
            return self.render_full_text(track.full_text, filename=filename)

        # Clamp progress
        progress = min(1.0, max(0.0, elapsed_ms / total_ms))

        # Find active word index
        active_idx = -1
        for i, word in enumerate(track.words):
            if word.start_ms <= elapsed_ms <= word.end_ms:
                active_idx = i
                break
        if active_idx < 0 and elapsed_ms < total_ms:
            # Between words — find nearest
            for i, word in enumerate(track.words):
                if elapsed_ms < word.start_ms:
                    active_idx = max(0, i - 1)
                    break

        shown_count = 0
        for i, word in enumerate(track.words):
            if word.start_ms <= elapsed_ms:
                shown_count = i + 1
            else:
                break

        shown_text = "".join(w.text for w in track.words[:shown_count])

        return self.render_full_text(
            shown_text,
            filename=filename,
            highlight_index=active_idx,
        )

    def render_entry_png(
        self,
        track: SubtitleTrack,
        entry_index: int,
        filename: str | None = None,
    ) -> str:
        """Render a single SRT entry as a transparent PNG strip.

        Args:
            track: SubtitleTrack.
            entry_index: 0-based index into track.entries.
            filename: Optional filename.

        Returns:
            Absolute path to the PNG file.
        """
        if entry_index < 0 or entry_index >= len(track.entries):
            raise IndexError(f"entry_index {entry_index} out of range")

        entry = track.entries[entry_index]

        if filename is None:
            filename = f"subtitle_{track.task_id}_entry{entry_index:03d}.png"

        return self.render_full_text(entry.text, filename=filename)

    def render_all_entries(
        self,
        track: SubtitleTrack,
    ) -> list[str]:
        """Render all SRT entries as individual PNG files.

        Returns:
            List of absolute PNG file paths.
        """
        paths: list[str] = []
        for i in range(len(track.entries)):
            p = self.render_entry_png(track, i)
            paths.append(p)
        return paths

    def render_frame_sequence(
        self,
        track: SubtitleTrack,
        fps: int = 25,
        prefix: str | None = None,
    ) -> list[str]:
        """Render a full frame sequence for FFmpeg image overlay.

        Generates one PNG per video frame (or per subtitle frame group),
        each with the correct progressive reveal and active word highlight.

        Args:
            track: SubtitleTrack with word timing.
            fps: Frames per second (for frame count calculation).
            prefix: Optional filename prefix. Default: track.task_id.

        Returns:
            List of absolute PNG file paths (one per frame).
        """
        total_ms = track.total_duration_ms
        if total_ms <= 0:
            return []

        frame_interval_ms = int(1000 / fps)
        total_frames = max(1, total_ms // frame_interval_ms)

        if prefix is None:
            prefix = track.task_id

        paths: list[str] = []
        for frame_idx in range(total_frames + 1):  # +1 for the final frame
            elapsed_ms = frame_idx * frame_interval_ms
            filename = f"subtitle_{prefix}_f{frame_idx:05d}.png"
            p = self.render_track_frame_by_ms(track, elapsed_ms, filename=filename)
            paths.append(p)

        logger.info("Frame sequence rendered: %d frames for %s",
                     len(paths), track.task_id)
        return paths

    # ── utility ────────────────────────────────────────────────────

    def render_to_rgba(
        self,
        text: str,
        highlight_index: int = -1,
    ) -> np.ndarray:
        """Render subtitle text to an in-memory RGBA numpy array.

        Returns RGBA uint8 array (height, width, 4).
        """
        from PIL import Image, ImageDraw
        import numpy as np

        style = self.style
        width, height = style.width, style.height
        font = self._get_font()

        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Background bar
        bg_rgba = (*style.bg_color, int(255 * style.bg_alpha))
        pad = style.padding
        draw.rounded_rectangle(
            [(pad, pad), (width - pad, height - pad)],
            radius=12, fill=bg_rgba,
        )

        chars = list(text)
        if not chars:
            return np.array(img)

        char_widths = []
        for ch in chars:
            bbox = draw.textbbox((0, 0), ch, font=font)
            char_widths.append(bbox[2] - bbox[0])

        total_text_w = sum(char_widths)
        start_x = (width - total_text_w) / 2
        sample_bbox = draw.textbbox((0, 0), "测", font=font)
        text_h = sample_bbox[3] - sample_bbox[1]
        y = (height - text_h) / 2

        x = start_x
        for i, ch in enumerate(chars):
            draw.text((x + 2, y + 2), ch, font=font, fill=(0, 0, 0, 140))
            if i == highlight_index and style.highlight_active:
                color = (*style.highlight_color, 255)
            else:
                color = (*style.text_color, 255)
            draw.text((x, y), ch, font=font, fill=color)
            x += char_widths[i]

        return np.array(img)

    def clear_pngs(self, prefix: str | None = None) -> int:
        """Delete PNG files. If prefix is given, only delete matching files.

        Returns count of deleted files.
        """
        if not self.output_dir.exists():
            return 0
        count = 0
        pattern = f"subtitle_{prefix}_*.png" if prefix else "*.png"
        for f in self.output_dir.glob(pattern):
            f.unlink()
            count += 1
        return count
