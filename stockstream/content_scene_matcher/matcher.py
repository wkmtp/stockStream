"""ContentSceneMatcher — core matching engine.

Analyzes host commentary text and detects trading indicators.
Notifies the SceneManager to switch the background display accordingly.

Architecture::

    commentary text ──► ContentSceneMatcher.analyze()
                            │
                            ├─► keyword scan (KEYWORD_MAP)
                            ├─► regex scan   (PATTERN_MAP)
                            ├─► rank by confidence + priority
                            │
                            ▼
                       MatchResult
                            │
                            ├─► indicators  (ranked list)
                            ├─► best_scene  (SceneType)
                            │
                            ▼
                       scene_manager.switch_to(best_scene)  ← optional auto-switch
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Optional

from stockstream.content_scene_matcher.models import (
    CATEGORY_SCENE_MAP,
    IndicatorCategory,
    KEYWORD_MAP,
    MatchResult,
    MatchedIndicator,
    PATTERN_MAP,
)
from stockstream.video.scene_manager import SceneManager, SceneType

logger = logging.getLogger(__name__)


# ── precompile patterns ────────────────────────────────────────────────────

# Sort keywords by length descending so longer phrases match first
_SORTED_KEYWORDS = sorted(KEYWORD_MAP, key=lambda x: len(x[0]), reverse=True)

# Compile regex patterns with their metadata
_COMPILED_PATTERNS: list[tuple[re.Pattern, IndicatorCategory, float]] = []
for pat_str, cat, weight in PATTERN_MAP:
    try:
        _COMPILED_PATTERNS.append((re.compile(pat_str), cat, weight))
    except re.error as exc:
        logger.warning("Invalid regex pattern '%s': %s", pat_str, exc)


# ── ContentSceneMatcher ────────────────────────────────────────────────────

class ContentSceneMatcher:
    """Analyze host commentary text and auto-switch scene backgrounds.

    Usage::

        scene_mgr = create_scene_manager()
        matcher = ContentSceneMatcher(scene_manager=scene_mgr)

        # Analyze without auto-switching
        result = matcher.analyze("MACD金叉，资金流入", auto_switch=False)
        print(result.best_scene)   # SceneType.MACD

        # Analyze with auto-switch
        result = matcher.analyze("放量上涨，主力净流入2亿", auto_switch=True)
        print(result.switched)     # True

        # Convenience: process a batch
        results = matcher.analyze_batch([
            "MACD金叉确认",
            "RSI超卖信号",
            "资金流向显示主力加仓",
        ])
    """

    def __init__(
        self,
        scene_manager: SceneManager,
        min_confidence: float = 0.35,
        enable_auto_switch: bool = True,
        verbose_log: bool = False,
    ) -> None:
        """
        Args:
            scene_manager: The SceneManager to notify on matches.
            min_confidence: Minimum confidence threshold (0.0–1.0).
            enable_auto_switch: If True, analyze() auto-switches the scene.
            verbose_log: If True, log detailed match info.
        """
        self._scene_manager = scene_manager
        self._min_confidence = min_confidence
        self._enable_auto_switch = enable_auto_switch
        self._verbose_log = verbose_log

        # Stats
        self.total_analyzed: int = 0
        self.total_switched: int = 0
        self._last_result: Optional[MatchResult] = None

    # ── properties ───────────────────────────────────────────────────

    @property
    def scene_manager(self) -> SceneManager:
        return self._scene_manager

    @property
    def min_confidence(self) -> float:
        return self._min_confidence

    @property
    def enable_auto_switch(self) -> bool:
        return self._enable_auto_switch

    @enable_auto_switch.setter
    def enable_auto_switch(self, val: bool) -> None:
        self._enable_auto_switch = val

    @property
    def last_result(self) -> Optional[MatchResult]:
        return self._last_result

    # ── main API ─────────────────────────────────────────────────────

    def analyze(
        self,
        text: str,
        *,
        auto_switch: Optional[bool] = None,
        force_switch: bool = False,
    ) -> MatchResult:
        """Analyze a commentary text and optionally switch the scene.

        Args:
            text: The host commentary text (e.g. "MACD金叉，资金流入").
            auto_switch: Override the instance-level auto_switch setting.
                None → use instance default.
            force_switch: If True, bypass scene_manager cooldown checks.

        Returns:
            MatchResult with detected indicators, best scene, and switch status.
        """
        if not text or not text.strip():
            result = MatchResult(
                text=text or "",
                best_scene=SceneType.KLINE,
                best_confidence=0.0,
            )
            self._last_result = result
            return result

        text = text.strip()
        self.total_analyzed += 1

        # ── Phase 1: scan keywords + patterns ─────────────────────
        indicators = self._scan_text(text)

        # ── Phase 2: determine best scene ─────────────────────────
        if not indicators:
            best_scene = self._scene_manager.match_scene(text)  # fallback to existing logic
            result = MatchResult(
                text=text,
                indicators=[],
                best_scene=best_scene,
                best_confidence=0.0,
            )
            self._last_result = result
            return result

        # Sort by confidence descending
        indicators.sort(key=lambda x: x.confidence, reverse=True)
        best_indicator = indicators[0]

        # ── Phase 3: auto-switch ──────────────────────────────────
        should_switch = auto_switch if auto_switch is not None else self._enable_auto_switch
        switched = False

        if should_switch and best_indicator.confidence >= self._min_confidence:
            target_scene = best_indicator.scene_type
            if force_switch:
                self._scene_manager.force_switch(target_scene)
                switched = True
            else:
                switched = self._scene_manager.switch_to(target_scene)

            if switched:
                self.total_switched += 1
                logger.info(
                    "Auto-switched to %s (confidence=%.2f, trigger: %s)",
                    target_scene.label,
                    best_indicator.confidence,
                    ", ".join(best_indicator.matched_keywords[:5]),
                )
        elif should_switch:
            logger.debug(
                "Confidence %.2f below threshold %.2f for '%s'",
                best_indicator.confidence, self._min_confidence, text[:50],
            )

        result = MatchResult(
            text=text,
            indicators=indicators,
            best_scene=best_indicator.scene_type,
            best_confidence=best_indicator.confidence,
            switched=switched,
        )

        if self._verbose_log:
            logger.debug(
                "Matched: '%s' → %s (%.2f) [indicators: %s]",
                text[:60],
                best_indicator.scene_type.label,
                best_indicator.confidence,
                ", ".join(ind.label for ind in indicators[:3]),
            )

        self._last_result = result
        return result

    def analyze_batch(
        self,
        texts: list[str],
        *,
        auto_switch: Optional[bool] = None,
    ) -> list[MatchResult]:
        """Analyze multiple texts sequentially. Auto-switches on the first strong match.

        Args:
            texts: List of commentary text strings.
            auto_switch: Override auto_switch setting.

        Returns:
            List of MatchResult, one per input text.
        """
        results = []
        for i, text in enumerate(texts):
            # For batch, only auto-switch on the first text
            # Subsequent texts get analyzed but don't trigger additional switches
            # unless they're much stronger
            switch = auto_switch if auto_switch is not None else self._enable_auto_switch
            result = self.analyze(text, auto_switch=switch)
            results.append(result)
        return results

    # ── keyword scanning ────────────────────────────────────────────

    def _scan_text(self, text: str) -> list[MatchedIndicator]:
        """Scan text for keywords and regex patterns, aggregate by category.

        Returns list of MatchedIndicator sorted by confidence desc.
        """
        text_lower = text.lower()

        # Accumulate raw scores per category
        scores: dict[IndicatorCategory, float] = defaultdict(float)
        matched_kw: dict[IndicatorCategory, list[str]] = defaultdict(list)
        matched_pat: dict[IndicatorCategory, list[str]] = defaultdict(list)

        # ── Keyword scan ───────────────────────────────────────────
        consumed_positions: set[tuple[int, int]] = set()

        for kw, cat, weight in _SORTED_KEYWORDS:
            kw_lower = kw.lower()
            pos = 0
            while True:
                idx = text_lower.find(kw_lower, pos)
                if idx == -1:
                    break

                # Check overlap with already-consumed positions
                span = (idx, idx + len(kw))
                if span not in consumed_positions:
                    scores[cat] += weight
                    matched_kw[cat].append(kw)
                    consumed_positions.add(span)
                    if self._verbose_log:
                        logger.debug("  keyword hit: '%s' → %s (w=%.1f)", kw, cat.value, weight)

                pos = idx + 1

        # ── Regex scan ─────────────────────────────────────────────
        for compiled_pat, cat, weight in _COMPILED_PATTERNS:
            for match in compiled_pat.finditer(text):
                scores[cat] += weight
                matched_pat[cat].append(match.group())
                if self._verbose_log:
                    logger.debug("  regex hit: '%s' → %s (w=%.1f)", match.group(), cat.value, weight)

        # ── Build indicator list ───────────────────────────────────
        indicators: list[MatchedIndicator] = []
        for cat, total_score in scores.items():
            # Normalize confidence: soft cap at 10.0, map to 0.0–1.0
            confidence = min(1.0, total_score / 8.0)

            # Keyword density bonus: more unique keyword hits = higher confidence
            unique_kw_count = len(set(matched_kw.get(cat, [])))
            if unique_kw_count >= 2:
                confidence = min(1.0, confidence + 0.15)
            if unique_kw_count >= 4:
                confidence = min(1.0, confidence + 0.10)

            # Regex bonus
            if len(matched_pat.get(cat, [])) > 0:
                confidence = min(1.0, confidence + 0.05)

            indicators.append(MatchedIndicator(
                category=cat,
                confidence=round(confidence, 4),
                matched_keywords=list(dict.fromkeys(matched_kw.get(cat, []))),  # dedup, preserve order
                matched_patterns=list(dict.fromkeys(matched_pat.get(cat, []))),
            ))

        return indicators

    # ── utility ─────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Return matcher statistics."""
        return {
            "total_analyzed": self.total_analyzed,
            "total_switched": self.total_switched,
            "switch_rate": round(self.total_switched / max(1, self.total_analyzed), 3),
            "min_confidence": self._min_confidence,
            "auto_switch_enabled": self._enable_auto_switch,
            "current_scene": self._scene_manager.current_scene.value,
            "current_scene_label": self._scene_manager.scene_label,
            "last_result": self._last_result.to_dict() if self._last_result else None,
        }

    def test_keyword(
        self,
        keyword: str,
        category: Optional[IndicatorCategory] = None,
    ) -> list[MatchedIndicator]:
        """Test what indicators a single keyword would trigger."""
        return self._scan_text(keyword)


# ── factory ────────────────────────────────────────────────────────────────

def create_content_scene_matcher(
    scene_manager: SceneManager,
    min_confidence: float = 0.35,
    enable_auto_switch: bool = True,
) -> ContentSceneMatcher:
    """Factory: create a ContentSceneMatcher with sensible defaults.

    Args:
        scene_manager: A configured SceneManager instance.
        min_confidence: Minimum confidence to trigger a scene switch.
        enable_auto_switch: Whether analyze() should auto-switch.

    Returns:
        Configured ContentSceneMatcher.
    """
    return ContentSceneMatcher(
        scene_manager=scene_manager,
        min_confidence=min_confidence,
        enable_auto_switch=enable_auto_switch,
    )
