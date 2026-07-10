"""Live dashboard — real-time statistics display.

Displays:
- Current online viewers
- Like count
- Gift count/value
- Fan growth
- Danmu count
- View duration
- Stock analysis count
- Voice broadcast count

Real-time refresh.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LiveDashboard:
    """Central data store for all live room stats.

    Acts as a single source of truth for the dashboard.
    Updated by various agents and connectors in real-time.
    """

    # ── Real-time counters ───────────────────────────────────
    current_viewers: int = 0
    peak_viewers: int = 0
    total_likes: int = 0
    total_gifts: int = 0
    total_gift_value: float = 0.0
    total_comments: int = 0
    total_follows: int = 0
    total_unfollows: int = 0
    current_followers: int = 0

    # ── Platform breakdown ────────────────────────────────────
    platform_stats: dict[str, dict[str, Any]] = field(default_factory=dict)

    # ── Content stats ─────────────────────────────────────────
    stock_analysis_count: int = 0
    voice_broadcast_count: int = 0
    clip_count: int = 0
    segment_count: int = 0
    ad_count: int = 0
    traffic_cta_count: int = 0
    silence_interventions: int = 0

    # ── Timing ───────────────────────────────────────────────
    started_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)

    # ── Viewer engagement ─────────────────────────────────────
    avg_view_duration: float = 0.0
    danmu_rate: float = 0.0          # danmu per minute
    like_rate: float = 0.0           # likes per minute
    gift_rate: float = 0.0           # gifts per minute

    # ── Q&A stats ─────────────────────────────────────────────
    qa_count: int = 0
    qa_accepted: int = 0

    # ── Revenue metrics ───────────────────────────────────────
    estimated_revenue: float = 0.0    # 预估收入 (元)
    membership_count: int = 0

    @property
    def uptime_seconds(self) -> float:
        return max(0.0, time.time() - self.started_at)

    @property
    def uptime_str(self) -> str:
        sec = int(self.uptime_seconds)
        h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    @property
    def current_followers_net(self) -> int:
        return self.total_follows - self.total_unfollows

    @property
    def engagement_rate(self) -> float:
        """Interaction rate = (danmu + likes) / viewers * 100."""
        if self.current_viewers == 0:
            return 0.0
        return (self.total_comments + self.total_likes) / max(1, self.current_viewers) * 100

    @property
    def retention_rate(self) -> float:
        """Estimated retention rate."""
        if self.peak_viewers == 0:
            return 0.0
        return self.current_viewers / self.peak_viewers * 100

    # ── Update methods ───────────────────────────────────────

    def update_viewers(self, count: int) -> None:
        self.current_viewers = count
        if count > self.peak_viewers:
            self.peak_viewers = count
        self._touch()

    def add_likes(self, count: int) -> None:
        self.total_likes += count
        self._touch()

    def add_gift(self, count: int = 1, value: float = 0) -> None:
        self.total_gifts += count
        self.total_gift_value += value
        self._touch()

    def add_comment(self, count: int = 1) -> None:
        self.total_comments += count
        self._touch()

    def add_follow(self, count: int = 1) -> None:
        self.total_follows += count
        self.current_followers += count
        self._touch()

    def add_unfollow(self, count: int = 1) -> None:
        self.total_unfollows += count
        self.current_followers = max(0, self.current_followers - count)
        self._touch()

    def add_analysis(self) -> None:
        self.stock_analysis_count += 1
        self._touch()

    def add_broadcast(self) -> None:
        self.voice_broadcast_count += 1
        self._touch()

    def add_clip(self) -> None:
        self.clip_count += 1
        self._touch()

    def add_segment(self) -> None:
        self.segment_count += 1
        self._touch()

    def add_ad(self) -> None:
        self.ad_count += 1
        self._touch()

    def add_traffic_cta(self) -> None:
        self.traffic_cta_count += 1
        self._touch()

    def add_silence_intervention(self) -> None:
        self.silence_interventions += 1
        self._touch()

    def add_qa(self) -> None:
        self.qa_count += 1
        self._touch()

    def add_qa_accepted(self) -> None:
        self.qa_accepted += 1
        self._touch()

    def update_rates(self) -> None:
        """Recalculate per-minute rates."""
        minutes = max(1, self.uptime_seconds / 60)
        self.danmu_rate = round(self.total_comments / minutes, 1)
        self.like_rate = round(self.total_likes / minutes, 1)
        self.gift_rate = round(self.total_gifts / minutes, 1)

    def _touch(self) -> None:
        self.last_updated = time.time()

    # ── Full snapshot ─────────────────────────────────────────

    def to_dict(self) -> dict:
        self.update_rates()
        return {
            # Basic
            "uptime": self.uptime_str,
            "uptime_seconds": round(self.uptime_seconds, 1),
            # Viewers
            "current_viewers": self.current_viewers,
            "peak_viewers": self.peak_viewers,
            "retention_rate": round(self.retention_rate, 1),
            # Engagement
            "total_likes": self.total_likes,
            "total_comments": self.total_comments,
            "total_gifts": self.total_gifts,
            "total_gift_value": round(self.total_gift_value, 2),
            # Fan growth
            "current_followers": self.current_followers,
            "total_follows": self.total_follows,
            "total_unfollows": self.total_unfollows,
            "net_growth": self.current_followers_net,
            # Content
            "segment_count": self.segment_count,
            "stock_analysis_count": self.stock_analysis_count,
            "voice_broadcast_count": self.voice_broadcast_count,
            "clip_count": self.clip_count,
            # Operations
            "ad_count": self.ad_count,
            "traffic_cta_count": self.traffic_cta_count,
            "silence_interventions": self.silence_interventions,
            # Q&A
            "qa_count": self.qa_count,
            "qa_accepted": self.qa_accepted,
            # Rates
            "danmu_per_minute": self.danmu_rate,
            "likes_per_minute": self.like_rate,
            "gifts_per_minute": self.gift_rate,
            "engagement_rate": round(self.engagement_rate, 1),
            # Revenue
            "estimated_revenue": round(self.estimated_revenue, 2),
            "membership_count": self.membership_count,
            # Meta
            "last_updated": self.last_updated,
        }
