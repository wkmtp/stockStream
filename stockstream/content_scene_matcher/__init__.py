"""Content Scene Matcher — auto-detect trading indicators from host commentary text.

Input:  host commentary text (e.g. "MACD金叉", "资金流入", "放量上涨", "RSI超卖")
Output: matched SceneType + confidence score, triggers scene_manager.switch_to()

Usage::

    from stockstream.content_scene_matcher import ContentSceneMatcher, MatchResult
    from stockstream.video.scene_manager import SceneManager

    scene_mgr = create_scene_manager()
    matcher = ContentSceneMatcher(scene_manager=scene_mgr)

    result = matcher.analyze("贵州茅台MACD金叉，主力资金净流入2.1亿")
    # result.scene_type → SceneType.MACD
    # result.confidence → 0.92
    # result.switched → True  (scene_manager was notified)
"""

from stockstream.content_scene_matcher.models import (
    MatchResult,
    MatchedIndicator,
    IndicatorCategory,
    KEYWORD_MAP,
    PATTERN_MAP,
    CATEGORY_SCENE_MAP,
    ALL_KEYWORDS_BY_SCENE,
)
from stockstream.content_scene_matcher.matcher import (
    ContentSceneMatcher,
    create_content_scene_matcher,
)

__all__ = [
    "ContentSceneMatcher",
    "create_content_scene_matcher",
    "MatchResult",
    "MatchedIndicator",
    "IndicatorCategory",
    "KEYWORD_MAP",
    "PATTERN_MAP",
    "CATEGORY_SCENE_MAP",
    "ALL_KEYWORDS_BY_SCENE",
]
