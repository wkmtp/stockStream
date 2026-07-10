"""Slide renderer — renders PPT-style financial slides as RGBA numpy arrays.

Uses PIL/Pillow for precise layout control, anti-aliased text, rounded cards,
and professional financial-page styling.

Each slide type gets a distinct colour scheme and layout:
    - 建仓推荐: green accent, card layout with rank badges
    - 补仓推荐: blue accent, card layout
    - 减仓提示: red accent, compact card layout
    - 清仓提示: orange accent, alert-style cards
    - 风险提示: amber accent, large text panel
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from stockstream.ai_slide_generator.models import (
    SlideConfig,
    SlideData,
    SlideResult,
    SlideTemplate,
    SlideType,
    StockSlideCard,
    OpenPositionSlide,
    AddPositionSlide,
    ReducePositionSlide,
    ClearPositionSlide,
    RiskWarningSlide,
)

logger = logging.getLogger(__name__)


# ── Template registry ───────────────────────────────────────────────────

_SLIDE_TEMPLATES: dict[SlideType, SlideTemplate] = {
    SlideType.OPEN_POSITION: OpenPositionSlide,
    SlideType.ADD_POSITION: AddPositionSlide,
    SlideType.REDUCE_POSITION: ReducePositionSlide,
    SlideType.CLEAR_POSITION: ClearPositionSlide,
    SlideType.RISK_WARNING: RiskWarningSlide,
}


# ── Font discovery ──────────────────────────────────────────────────────

def _find_font_path() -> Optional[str]:
    """Locate a Chinese-capable TrueType font on the current system."""
    import os
    import platform

    system = platform.system()
    candidates: list[str] = []

    if system == "Windows":
        windir = os.environ.get("WINDIR", "C:\\Windows")
        fonts_dir = os.path.join(windir, "Fonts")
        candidates = [
            os.path.join(fonts_dir, f)
            for f in ["msyh.ttc", "msyhbd.ttc", "simhei.ttf",
                       "simsun.ttc", "msyh.ttf"]
        ]
    elif system == "Darwin":
        candidates = [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        ]

    for path in candidates:
        if os.path.isfile(path):
            return path

    return None


# ── Colour helpers ──────────────────────────────────────────────────────

def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _hex_to_rgba(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    return _hex_to_rgb(hex_color) + (alpha,)


# ── Utility: rounded rectangle ──────────────────────────────────────────

def _draw_rounded_rect(draw, xy: tuple[int, int, int, int],
                       radius: int, fill, outline=None, width: int = 1):
    """Draw a rounded rectangle using PIL."""
    from PIL import ImageDraw
    x1, y1, x2, y2 = xy
    r = radius

    # Fill
    if fill:
        draw.rounded_rectangle(xy, radius=r, fill=fill)

    # Outline
    if outline:
        draw.rounded_rectangle(xy, radius=r, outline=outline, width=width)


# ── Text drawing helpers ────────────────────────────────────────────────

def _draw_text_centered(draw, text: str, xy: tuple[int, int],
                        font, fill) -> None:
    """Draw text centered on (x, y)."""
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text((xy[0] - tw // 2, xy[1] - th // 2), text, font=font, fill=fill)


def _draw_text_box(draw, text: str, xy: tuple[int, int, int, int],
                   font, fill, align: str = "left",
                   line_spacing: int = 8) -> int:
    """Draw text within a bounding box with word wrapping. Returns y position after text."""
    from PIL import ImageDraw
    x, y, w, h = xy
    max_x = x + w
    words = list(text)
    lines: list[str] = []
    current_line = ""

    for ch in words:
        test = current_line + ch
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] > w and current_line:
            lines.append(current_line)
            current_line = ch
        else:
            current_line = test
    if current_line:
        lines.append(current_line)

    cursor_y = y
    for line in lines:
        if cursor_y + font.size > y + h:
            break
        if align == "center":
            lb = draw.textbbox((0, 0), line, font=font)
            lx = x + (w - (lb[2] - lb[0])) // 2
        elif align == "right":
            lb = draw.textbbox((0, 0), line, font=font)
            lx = x + w - (lb[2] - lb[0])
        else:
            lx = x
        draw.text((lx, cursor_y), line, font=font, fill=fill)
        cursor_y += font.size + line_spacing

    return cursor_y


# ── Card renderer ───────────────────────────────────────────────────────

def _render_stock_card(
    draw,
    card: StockSlideCard,
    x: int, y: int, w: int, h: int,
    config: SlideConfig,
    template: SlideTemplate,
    title_font, body_font, small_font, code_font, reason_font,
    accent_rgb: tuple[int, int, int, int],
) -> None:
    """Render one stock recommendation card."""
    r = config.card_radius
    pad = config.card_padding

    # Card background
    bg_card = _hex_to_rgba(config.bg_card)
    border = _hex_to_rgba(template.card_border_color)
    _draw_rounded_rect(draw, (x, y, x + w, y + h), r,
                       fill=bg_card, outline=border, width=2)

    # Left accent bar
    bar_w = 6
    _draw_rounded_rect(draw, (x + 2, y + r, x + 2 + bar_w, y + h - r),
                       r // 2, fill=border)

    # ── Rank badge ──
    badge_r = 22
    badge_cx = x + pad + 20
    badge_cy = y + pad + 24
    badge_bg = _hex_to_rgba(template.header_bg)
    _draw_rounded_rect(draw, (badge_cx - badge_r, badge_cy - badge_r,
                               badge_cx + badge_r, badge_cy + badge_r),
                        badge_r, fill=badge_bg, outline=border, width=2)
    rank_text = f"#{card.rank}"
    _draw_text_centered(draw, rank_text, (badge_cx, badge_cy),
                        body_font, accent_rgb)

    # ── Stock name + symbol ──
    name_x = badge_cx + badge_r + 18
    draw.text((name_x, y + pad + 4), card.name, font=title_font,
              fill=_hex_to_rgba(config.text_primary))
    name_w = draw.textbbox((0, 0), card.name, font=title_font)[2]
    draw.text((name_x + name_w + 14, y + pad + 10), card.symbol,
              font=code_font, fill=_hex_to_rgba(config.text_secondary))

    # ── Price row ──
    price_y = y + pad + title_font.size + 22
    price_text = f"¥{card.close:.2f}" if card.close else "--"
    price_color = config.accent_green if card.is_positive else config.accent_red
    draw.text((name_x, price_y), price_text, font=body_font,
              fill=_hex_to_rgba(price_color))

    # Change percentage
    if card.daily_change_pct is not None:
        chg = card.daily_change_pct
        sign = "+" if chg >= 0 else ""
        chg_text = f" {sign}{chg:.2f}%"
        pw = draw.textbbox((0, 0), price_text, font=body_font)[2]
        draw.text((name_x + pw + 10, price_y), chg_text,
                  font=body_font, fill=_hex_to_rgba(price_color))

    # ── Technical indicators row ──
    info_y = price_y + body_font.size + 16
    indicators: list[tuple[str, str]] = []
    if card.ma20 is not None:
        indicators.append(("MA20", f"{card.ma20:.2f}"))
    if card.ma20_deviation_pct is not None:
        indicators.append(("偏离", f"{card.ma20_deviation_pct:+.1f}%"))
    if card.rsi14 is not None:
        indicators.append(("RSI14", f"{card.rsi14:.0f}"))
    if card.turnover_pct is not None:
        indicators.append(("换手", f"{card.turnover_pct:.2f}%"))
    if card.money_flow is not None:
        mf = card.money_flow
        mf_str = f"{mf/1e8:.2f}亿" if abs(mf) >= 1e8 else f"{mf/1e4:.0f}万"
        indicators.append(("资金", mf_str))

    ix = name_x
    for label, value in indicators:
        lbl_text = f"{label} {value}"
        draw.text((ix, info_y), lbl_text, font=small_font,
                  fill=_hex_to_rgba(config.text_secondary))
        lw = draw.textbbox((0, 0), lbl_text, font=small_font)[2]
        ix += lw + 18
        if ix > x + w - pad - 40:
            break

    # ── Reasons as tags ──
    reason_y = info_y + small_font.size + 14
    rx = name_x
    ry = reason_y
    tag_pad = config.reason_tag_padding
    tag_gap = config.reason_tag_gap
    reason_bg = _hex_to_rgba(template.reason_bg)
    reason_fg = _hex_to_rgba(template.reason_text_color)
    max_reason_w = w - pad * 2 - 40

    for reason in card.reasons:
        rb = draw.textbbox((0, 0), reason, font=reason_font)
        rw = rb[2] - rb[0] + tag_pad * 2
        rh = rb[3] - rb[1] + tag_pad

        if rx + rw > x + w - pad:
            rx = name_x
            ry += rh + tag_gap
            if ry + rh > y + h - pad:
                break

        _draw_rounded_rect(draw, (rx, ry, rx + rw, ry + rh),
                           tag_pad // 2, fill=reason_bg, outline=border, width=1)
        draw.text((rx + tag_pad, ry + tag_pad // 2 - 1), reason,
                  font=reason_font, fill=reason_fg)
        rx += rw + tag_gap


# ── Header renderer ─────────────────────────────────────────────────────

def _render_header(
    draw,
    data: SlideData,
    config: SlideConfig,
    template: SlideTemplate,
    title_font, subtitle_font,
) -> None:
    """Render the slide header area with gradient background."""
    from PIL import ImageDraw

    # Header background
    h_bg = _hex_to_rgba(template.header_bg)
    _draw_rounded_rect(draw, (config.margin_left, config.margin_top,
                               config.margin_left + config.content_width,
                               config.margin_top + config.header_height),
                       config.card_radius, fill=h_bg)

    # Left accent bar
    accent = _hex_to_rgba(template.card_border_color)
    bar_h = 80
    bar_y = config.margin_top + (config.header_height - bar_h) // 2
    draw.rectangle(
        (config.margin_left + 30, bar_y,
         config.margin_left + 36, bar_y + bar_h),
        fill=accent,
    )

    # Title
    tx = config.margin_left + 58
    ty = config.margin_top + 24
    draw.text((tx, ty), data.title, font=title_font,
              fill=_hex_to_rgba(config.text_primary))

    # Subtitle
    if data.subtitle:
        sy = ty + title_font.size + 14
        draw.text((tx, sy), data.subtitle, font=subtitle_font,
                  fill=_hex_to_rgba(config.text_secondary))

    # Right side: market summary + timestamp
    if data.market_summary or data.extra_note:
        rx = config.margin_left + config.content_width - config.card_padding
        ry = config.margin_top + 30
        if data.market_summary:
            ms_bbox = draw.textbbox((0, 0), data.market_summary, font=subtitle_font)
            draw.text((rx - (ms_bbox[2] - ms_bbox[0]), ry),
                      data.market_summary, font=subtitle_font,
                      fill=_hex_to_rgba(config.text_secondary),
                      anchor=None)
        if data.extra_note:
            rny = ry + subtitle_font.size + 6
            en_bbox = draw.textbbox((0, 0), data.extra_note, font=subtitle_font)
            draw.text((rx - (en_bbox[2] - en_bbox[0]), rny),
                      data.extra_note, font=subtitle_font,
                      fill=_hex_to_rgba(config.text_tertiary))


# ── Footer renderer ─────────────────────────────────────────────────────

def _render_footer(
    draw,
    data: SlideData,
    config: SlideConfig,
    small_font,
) -> None:
    """Render the bottom disclaimer bar."""
    fy = config.height - config.margin_bottom - small_font.size - 8
    divider = _hex_to_rgba(config.divider)
    draw.line(
        (config.margin_left, fy - 10,
         config.margin_left + config.content_width, fy - 10),
        fill=divider, width=1,
    )
    footer_text = data.disclaimer
    draw.text((config.margin_left, fy + 6), footer_text,
              font=small_font, fill=_hex_to_rgba(config.text_tertiary))


# ── Risk warning special layout ─────────────────────────────────────────

def _render_risk_warning(
    draw,
    data: SlideData,
    config: SlideConfig,
    body_font, small_font,
) -> None:
    """Render the standalone risk warning slide (large text panel)."""
    import textwrap

    # Warning icon panel
    icon_size = 80
    icon_x = config.margin_left + (config.content_width - icon_size) // 2
    icon_y = config.margin_top + config.header_height + 40
    warning_bg = _hex_to_rgba("#2D1F0A")
    _draw_rounded_rect(draw, (icon_x, icon_y, icon_x + icon_size,
                               icon_y + icon_size),
                       config.card_radius, fill=warning_bg)

    # "⚠" symbol
    _draw_text_centered(draw, "⚠", (icon_x + icon_size // 2, icon_y + icon_size // 2),
                        body_font, _hex_to_rgba(config.accent_orange))

    # Risk text panel
    panel_x = config.margin_left + 80
    panel_y = icon_y + icon_size + 30
    panel_w = config.content_width - 160
    panel_h = config.content_height - config.header_height - icon_size - 120
    panel_bg = _hex_to_rgba(config.bg_card)
    _draw_rounded_rect(draw, (panel_x, panel_y, panel_x + panel_w,
                               panel_y + panel_h),
                       config.card_radius, fill=panel_bg,
                       outline=_hex_to_rgba(config.border), width=1)

    # Risk text
    text_x = panel_x + config.card_padding
    text_y = panel_y + config.card_padding
    text_w = panel_w - config.card_padding * 2
    text_h = panel_h - config.card_padding * 2

    _draw_text_box(draw, data.risk_text or "投资有风险，入市需谨慎",
                   (text_x, text_y, text_w, text_h),
                   body_font, _hex_to_rgba(config.text_primary),
                   line_spacing=12)


# ── Main renderer class ─────────────────────────────────────────────────

class SlideRenderer:
    """Render PPT-style financial slides as RGBA numpy arrays."""

    def __init__(self, config: SlideConfig | None = None) -> None:
        self.cfg = config or SlideConfig()
        self._font_path = _find_font_path()
        self._fonts: dict[str, object] = {}

    def _get_font(self, name: str, size: int):
        """Get a PIL font with caching."""
        cache_key = f"{name}_{size}"
        if cache_key in self._fonts:
            return self._fonts[cache_key]

        from PIL import ImageFont

        try:
            if self._font_path:
                font = ImageFont.truetype(self._font_path, size)
            else:
                font = ImageFont.load_default()
        except Exception:
            font = ImageFont.load_default()

        self._fonts[cache_key] = font
        return font

    def render(self, data: SlideData) -> SlideResult:
        """Render a single slide page.

        Args:
            data: SlideData with stock cards, title, subtitle, etc.

        Returns:
            SlideResult containing the RGBA numpy array.
        """
        import time
        from PIL import Image, ImageDraw

        t_start = time.perf_counter()

        cfg = self.cfg
        template = _SLIDE_TEMPLATES.get(data.slide_type, RiskWarningSlide)

        # Create canvas
        img = Image.new("RGBA", (cfg.width, cfg.height),
                        _hex_to_rgba(cfg.bg_primary))
        draw = ImageDraw.Draw(img)

        # Fonts
        title_font = self._get_font("title", cfg.title_font_size)
        subtitle_font = self._get_font("subtitle", cfg.subtitle_font_size)
        body_font = self._get_font("body", cfg.body_font_size)
        small_font = self._get_font("small", cfg.small_font_size)
        code_font = self._get_font("code", cfg.stock_code_font_size)
        reason_font = self._get_font("reason", cfg.small_font_size - 2)
        accent_rgb = _hex_to_rgba(template.title_color)

        # ── Header ──
        _render_header(draw, data, cfg, template, title_font, subtitle_font)

        # ── Cards area ──
        cards_y = cfg.margin_top + cfg.header_height + cfg.card_gap
        cards_bottom = cfg.height - cfg.margin_bottom - small_font.size - 40

        if data.slide_type == SlideType.RISK_WARNING:
            _render_risk_warning(draw, data, cfg, body_font, small_font)
        elif data.cards:
            available_h = cards_bottom - cards_y
            max_cards = min(len(data.cards), cfg.max_cards_per_slide)
            card_h = min(
                (available_h - (max_cards - 1) * cfg.card_gap) // max_cards,
                240,
            )
            card_h = max(card_h, 160)
            card_w = cfg.content_width

            for i, card in enumerate(data.cards[:max_cards]):
                card_x = cfg.margin_left
                card_y = cards_y + i * (card_h + cfg.card_gap)
                if card_y + card_h > cards_bottom:
                    break

                _render_stock_card(
                    draw, card, card_x, card_y, card_w, card_h,
                    cfg, template,
                    title_font, body_font, small_font, code_font, reason_font,
                    accent_rgb,
                )

        # ── Footer ──
        _render_footer(draw, data, cfg, small_font)

        # Convert to numpy
        rgba = np.array(img, dtype=np.uint8)

        render_ms = (time.perf_counter() - t_start) * 1000.0

        # PNG bytes
        import io
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        return SlideResult(
            slide_type=data.slide_type,
            title=data.title,
            rgba=rgba,
            png_bytes=png_bytes,
            width=cfg.width,
            height=cfg.height,
            card_count=len(data.cards),
            generated_at=data.generated_at,
            render_time_ms=render_ms,
        )
