"""Subtitle renderer — renders Chinese subtitle text as semi-transparent overlay strips.

Uses PIL/Pillow to render text with proper anti-aliased font rendering.
Output is a numpy uint8 RGBA (H, W, 4) array ready for compositing.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


def _find_chinese_font_path() -> Optional[str]:
    """Return the path to a Chinese-capable TrueType font, or None."""
    import platform
    import os

    system = platform.system()
    candidates = []

    if system == "Windows":
        candidates = [
            os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", f)
            for f in ["msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc", "msyh.ttf"]
        ]
    elif system == "Darwin":
        candidates = [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
        ]
    else:
        candidates = [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansSC-Regular.otf",
        ]

    for path in candidates:
        if os.path.isfile(path):
            return path

    # PIL fallback — will use default font (may render tofu for CJK)
    return None


FONT_PATH = _find_chinese_font_path()
if FONT_PATH:
    logger.info("Subtitle font: %s", FONT_PATH)
else:
    logger.warning("No Chinese TTF font found; subtitles may display as □□□")


class SubtitleRenderer:
    """Render Chinese subtitle text strips for video overlay.

    Features:
    - Semi-transparent dark background bar
    - Smooth anti-aliased text
    - Automatic line wrapping
    - Configurable position, font size, colours

    Usage::

        renderer = SubtitleRenderer()
        sub_rgba = renderer.render("贵州茅台今日主力净流入超5亿元", width=1280, height=80)
        # sub_rgba.shape == (80, 1280, 4)
    """

    def __init__(
        self,
        font_path: str | None = None,
        font_size: int = 36,
        bg_alpha: float = 0.55,
        text_color: tuple[int, int, int] = (255, 255, 255),
        bg_color: tuple[int, int, int] = (0, 0, 0),
        padding: int = 12,
    ) -> None:
        self.font_path = font_path or FONT_PATH
        self.font_size = font_size
        self.bg_alpha = bg_alpha
        self.text_color = text_color
        self.bg_color = bg_color
        self.padding = padding
        self._pil_font = None

    # ── lazy font loading ──────────────────────────────────────────

    def _get_font(self):
        if self._pil_font is None:
            from PIL import ImageFont
            try:
                if self.font_path:
                    self._pil_font = ImageFont.truetype(self.font_path, self.font_size)
                else:
                    self._pil_font = ImageFont.load_default()
            except Exception as exc:
                logger.warning("Cannot load font %s: %s, using default", self.font_path, exc)
                self._pil_font = ImageFont.load_default()
        return self._pil_font

    # ── main API ───────────────────────────────────────────────────

    def render(
        self,
        text: str,
        width: int = 1280,
        height: int = 80,
        align: str = "center",
        speaker_label: str = "",
    ) -> np.ndarray:
        """Render a subtitle strip as an RGBA numpy array.

        Args:
            text: Subtitle text to display (Chinese + ASCII).
            width: Width in pixels of the output strip.
            height: Height in pixels of the output strip.
            align: Text alignment: "left", "center", or "right".
            speaker_label: Optional prefix label (e.g. "AI主播").

        Returns:
            numpy uint8 RGBA array (height, width, 4).
        """
        from PIL import Image, ImageDraw

        # Create RGBA canvas
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        font = self._get_font()

        # Draw semi-transparent background bar
        bg_rgba = (*self.bg_color, int(255 * self.bg_alpha))
        draw.rounded_rectangle(
            [(self.padding, self.padding),
             (width - self.padding, height - self.padding)],
            radius=12, fill=bg_rgba,
        )

        # Prepare display text with optional label
        display_text = text
        if speaker_label:
            display_text = f"[{speaker_label}] {text}"

        # Wrap text if needed
        lines = self._wrap_text(display_text, width - self.padding * 4, font, draw)

        # Calculate total text height and starting Y
        line_spacing = self.font_size + 6
        total_text_h = len(lines) * line_spacing
        y_start = (height - total_text_h) / 2

        for i, line in enumerate(lines):
            y = y_start + i * line_spacing
            bbox = draw.textbbox((0, 0), line, font=font)
            tw = bbox[2] - bbox[0]

            if align == "center":
                x = (width - tw) / 2
            elif align == "right":
                x = width - self.padding * 2 - tw
            else:
                x = self.padding * 2

            # Text shadow for readability
            draw.text((x + 2, y + 2), line, font=font, fill=(0, 0, 0, 160))
            # Main text
            draw.text((x, y), line, font=font, fill=(*self.text_color, 255))

        return np.array(img)

    def render_simple(
        self,
        text: str,
        width: int = 1280,
        height: int = 80,
    ) -> np.ndarray:
        """Fast simple render without background bar — transparent text only."""
        from PIL import Image, ImageDraw

        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        font = self._get_font()

        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = (width - tw) / 2
        y = (height - th) / 2

        draw.text((x + 2, y + 2), text, font=font, fill=(0, 0, 0, 160))
        draw.text((x, y), text, font=font, fill=(*self.text_color, 255))

        return np.array(img)

    # ── helpers ────────────────────────────────────────────────────

    def _wrap_text(
        self, text: str, max_width: int, font, draw
    ) -> list[str]:
        """Simple greedy word wrapping for mixed CJK/ASCII text."""
        lines = []
        current = ""
        for ch in text:
            test = current + ch
            bbox = draw.textbbox((0, 0), test, font=font)
            if bbox[2] - bbox[0] > max_width and current:
                lines.append(current)
                current = ch
            else:
                current = test
        if current:
            lines.append(current)
        return lines or [text]

    # ── convenience: render with typewriter (逐字) animation support ──

    def render_progressive(
        self,
        text: str,
        progress: float,   # 0.0 → 1.0
        width: int = 1280,
        height: int = 80,
    ) -> np.ndarray:
        """Render subtitle with typewriter reveal effect.

        Args:
            text: Full subtitle text.
            progress: 0.0 (none shown) to 1.0 (fully shown).
        """
        shown_len = max(1, int(len(text) * progress))
        shown = text[:shown_len]
        if progress < 1.0:
            shown += "▎"  # cursor
        return self.render(shown, width=width, height=height)
