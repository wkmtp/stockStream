"""Dual-host live system data models.

Defines all enums, dataclasses and configuration for the AI finance talk show.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── Speaker ────────────────────────────────────────────────────

class Speaker(str, Enum):
    MALE = "male"       # 老股民, 沉稳专业
    FEMALE = "female"   # 新人, 活泼好奇


# ── Emotion ────────────────────────────────────────────────────

class Emotion(str, Enum):
    NEUTRAL = "neutral"
    HAPPY = "happy"
    EXCITED = "excited"
    SERIOUS = "serious"
    SURPRISED = "surprised"
    WARNING = "warning"
    THINKING = "thinking"
    HUMOROUS = "humorous"


# ── Avatar Action ──────────────────────────────────────────────

class AvatarAction(str, Enum):
    # Male actions
    NOD = "nod"               # 点头
    WAVE = "wave"             # 挥手
    THINK = "think"           # 思考
    POINT = "point"           # 指向
    CONFIDENT = "confident"   # 自信
    # Female actions
    SMILE = "smile"           # 微笑
    SURPRISE = "surprise"     # 惊讶
    THUMBS_UP = "thumbs_up"   # 点赞
    CURIOUS = "curious"       # 好奇
    LAUGH = "laugh"           # 笑
    # Shared
    IDLE = "idle"             # 待机
    GREETING = "greeting"     # 打招呼
    EXPLAIN = "explain"       # 讲解


EMOTION_ACTION_MAP: dict[Emotion, dict[Speaker, AvatarAction]] = {
    Emotion.NEUTRAL:    {Speaker.MALE: AvatarAction.IDLE,       Speaker.FEMALE: AvatarAction.IDLE},
    Emotion.HAPPY:      {Speaker.MALE: AvatarAction.NOD,        Speaker.FEMALE: AvatarAction.SMILE},
    Emotion.EXCITED:    {Speaker.MALE: AvatarAction.WAVE,       Speaker.FEMALE: AvatarAction.THUMBS_UP},
    Emotion.SERIOUS:    {Speaker.MALE: AvatarAction.CONFIDENT,  Speaker.FEMALE: AvatarAction.CURIOUS},
    Emotion.SURPRISED:  {Speaker.MALE: AvatarAction.THINK,      Speaker.FEMALE: AvatarAction.SURPRISE},
    Emotion.WARNING:    {Speaker.MALE: AvatarAction.POINT,      Speaker.FEMALE: AvatarAction.SURPRISE},
    Emotion.THINKING:   {Speaker.MALE: AvatarAction.THINK,      Speaker.FEMALE: AvatarAction.CURIOUS},
    Emotion.HUMOROUS:   {Speaker.MALE: AvatarAction.WAVE,       Speaker.FEMALE: AvatarAction.LAUGH},
}


# ── Dialogue ───────────────────────────────────────────────────

@dataclass()
class DialogTurn:
    """A single spoken line in the dialogue script."""
    speaker: Speaker
    text: str
    emotion: Emotion = Emotion.NEUTRAL
    action: AvatarAction = AvatarAction.IDLE
    duration_sec: float = 3.0       # estimated speaking time
    is_question: bool = False
    segment_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "speaker": self.speaker.value,
            "text": self.text,
            "emotion": self.emotion.value,
            "action": self.action.value,
            "duration_sec": self.duration_sec,
            "is_question": self.is_question,
            "segment_id": self.segment_id,
        }


@dataclass()
class DialogueScript:
    """Complete dialogue for one segment (stock/sector/news/etc)."""
    segment_id: str
    segment_type: ShowSegmentType
    topic: str                          # stock code, sector name, or headline
    turns: list[DialogTurn] = field(default_factory=list)
    created_at: float = field(default_factory=time.monotonic)

    @property
    def male_lines(self) -> list[str]:
        return [t.text for t in self.turns if t.speaker == Speaker.MALE]

    @property
    def female_lines(self) -> list[str]:
        return [t.text for t in self.turns if t.speaker == Speaker.FEMALE]

    @property
    def full_text(self) -> str:
        return "\n".join(f"[{t.speaker.value}] {t.text}" for t in self.turns)

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "segment_type": self.segment_type.value,
            "topic": self.topic,
            "turns": [t.to_dict() for t in self.turns],
            "turn_count": len(self.turns),
        }


# ── Show Segment Types ─────────────────────────────────────────

class ShowSegmentType(str, Enum):
    STOCK_ANALYSIS = "stock_analysis"         # 个股分析 (每3分钟)
    HOT_SECTOR = "hot_sector"                  # 热点板块 (每10分钟)
    NEWS_COMMENTARY = "news_commentary"        # 新闻点评 (每15分钟)
    FINANCE_FUN = "finance_fun"               # 财经趣闻 (每20分钟)
    AUDIENCE_QA = "audience_qa"               # 粉丝互动 (每30分钟)
    MARKET_REVIEW = "market_review"           # 市场复盘 (每60分钟)
    OPENING = "opening"                       # 开场白
    CLOSING = "closing"                       # 结束语
    DEBATE = "debate"                         # 多空辩论
    HUMOR = "humor"                           # 财经段子


# ── Director schedule slots ────────────────────────────────────

@dataclass()
class ScheduleSlot:
    """A scheduled segment in the show rundown."""
    segment_type: ShowSegmentType
    interval_minutes: int          # how often this slot fires
    max_duration_sec: int          # max segment duration
    priority: int = 5              # lower = higher priority


DEFAULT_SCHEDULE: list[ScheduleSlot] = [
    ScheduleSlot(ShowSegmentType.OPENING,          1,   20,  priority=0),     # 开场第一件事
    ScheduleSlot(ShowSegmentType.STOCK_ANALYSIS,   3,   45,  priority=2),
    ScheduleSlot(ShowSegmentType.HOT_SECTOR,       10,  60,  priority=3),
    ScheduleSlot(ShowSegmentType.NEWS_COMMENTARY,  15,  40,  priority=4),
    ScheduleSlot(ShowSegmentType.FINANCE_FUN,      20,  30,  priority=5),
    ScheduleSlot(ShowSegmentType.AUDIENCE_QA,      30,  45,  priority=6),
    ScheduleSlot(ShowSegmentType.MARKET_REVIEW,    60,  90,  priority=7),
]


# ── DualHost Config ────────────────────────────────────────────

@dataclass()
class DualHostConfig:
    """Configuration for the dual-host live system."""
    # TTS voices — true dual-voice via separate ONNX models
    male_voice: str = "zh_CN-chaowen-medium"       # 男声 - 超文
    female_voice: str = "zh_CN-huayan-medium"       # 女声 - 华燕
    male_model_path: str = "models/zh_CN-chaowen-medium.onnx"
    female_model_path: str = "models/zh_CN-huayan-medium.onnx"
    # Timing
    tick_seconds: float = 1.0
    dialogue_turns_per_stock: tuple[int, int] = (3, 6)   # min, max
    inter_speaker_pause: float = 0.5            # pause between speakers (seconds)
    # Content
    enable_debate: bool = True
    enable_humor: bool = True
    enable_storytelling: bool = True
    enable_audience: bool = True
    enable_news: bool = True
    enable_avatar: bool = True
    # Schedule overrides
    schedule: list[ScheduleSlot] = field(default_factory=lambda: DEFAULT_SCHEDULE.copy())
    # TTS output
    tts_output_dir: str = "data/dual_host_audio"
