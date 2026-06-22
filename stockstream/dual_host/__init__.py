"""AI 财经相声直播间 — 双人数字人直播系统。

提供：
- 男女双主播对话脚本生成
- 情绪引擎 + 通俗化表达
- 多空辩论 + 财经段子
- 新闻点评 + 观众互动
- 双人TTS + 数字人动作
- 导演调度系统

Usage::

    from stockstream.dual_host.service import DualHostService
    svc = DualHostService(analysis=analysis_svc, tts=tts_svc, stream=stream_svc)
    await svc.start()  # 启动直播
"""
from stockstream.dual_host.models import (
    AvatarAction,
    DialogTurn,
    DialogueScript,
    DualHostConfig,
    Emotion,
    EMOTION_ACTION_MAP,
    ScheduleSlot,
    ShowSegmentType,
    Speaker,
)
from stockstream.dual_host.emotion_engine import EmotionEngine
from stockstream.dual_host.storytelling_engine import StorytellingEngine
from stockstream.dual_host.dialogue_generator import DialogueGenerator
from stockstream.dual_host.debate_engine import DebateEngine
from stockstream.dual_host.finance_humor_engine import FinanceHumorEngine
from stockstream.dual_host.news_commentator import NewsCommentator
from stockstream.dual_host.director_agent import DirectorAgent
from stockstream.dual_host.audience_agent import AudienceAgent
from stockstream.dual_host.live_comment_fusion import LiveCommentFusion
from stockstream.dual_host.dual_voice_tts import DualVoiceTTS
from stockstream.dual_host.avatar_action_engine import AvatarActionEngine
from stockstream.dual_host.service import DualHostService

__version__ = "0.1.0"
__all__ = [
    # Service
    "DualHostService",
    # Models
    "Emotion", "AvatarAction", "Speaker",
    "DialogTurn", "DialogueScript", "ShowSegmentType",
    "DualHostConfig", "ScheduleSlot", "EMOTION_ACTION_MAP",
    # Engines
    "EmotionEngine", "StorytellingEngine",
    "DialogueGenerator", "DebateEngine",
    "FinanceHumorEngine", "NewsCommentator",
    "DirectorAgent", "AudienceAgent",
    "LiveCommentFusion", "DualVoiceTTS",
    "AvatarActionEngine",
]
