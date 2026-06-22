"""Fan growth tracker — real-time follower monitoring and trend analysis.

Features:
- Real-time follower count tracking
- New follower detection
- Unfollow detection
- Hourly growth statistics
- Daily reports
- Trend visualization data
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FanSnapshot:
    """A single point-in-time fan count snapshot."""
    timestamp: float
    platform: str
    follower_count: int
    new_follows: int = 0
    unfollows: int = 0

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "platform": self.platform,
            "follower_count": self.follower_count,
            "new_follows": self.new_follows,
            "unfollows": self.unfollows,
            "time_str": datetime.fromtimestamp(self.timestamp).isoformat(),
        }


@dataclass
class HourlyReport:
    """Hourly fan growth report."""
    hour_start: float
    platform: str
    start_count: int
    end_count: int
    new_follows: int
    unfollows: int
    net_growth: int

    @property
    def growth_rate(self) -> float:
        if self.start_count == 0:
            return 0.0
        return self.net_growth / self.start_count

    def to_dict(self) -> dict:
        return {
            "hour": datetime.fromtimestamp(self.hour_start).strftime("%H:00"),
            "platform": self.platform,
            "start_count": self.start_count,
            "end_count": self.end_count,
            "new_follows": self.new_follows,
            "unfollows": self.unfollows,
            "net_growth": self.net_growth,
            "growth_rate": round(self.growth_rate * 100, 2),
        }


@dataclass
class DailyReport:
    """Daily fan growth report."""
    date: str  # YYYY-MM-DD
    platform: str
    start_count: int
    end_count: int
    new_follows: int
    unfollows: int
    peak_count: int
    hourly_reports: list[HourlyReport] = field(default_factory=list)

    @property
    def net_growth(self) -> int:
        return self.new_follows - self.unfollows

    @property
    def growth_rate(self) -> float:
        if self.start_count == 0:
            return 0.0
        return self.net_growth / self.start_count

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "platform": self.platform,
            "start_count": self.start_count,
            "end_count": self.end_count,
            "new_follows": self.new_follows,
            "unfollows": self.unfollows,
            "net_growth": self.net_growth,
            "peak_count": self.peak_count,
            "growth_rate_pct": round(self.growth_rate * 100, 2),
            "hourly_reports": [h.to_dict() for h in self.hourly_reports],
        }


class FanGrowthTracker:
    """Real-time follower growth monitoring.

    Usage::

        tracker = FanGrowthTracker()
        tracker.update("张三", "follow", 1500, "douyin")
        tracker.update("李四", "unfollow", 1499, "douyin")
        report = tracker.get_hourly_report("douyin")
    """

    def __init__(self, history_size: int = 86400) -> None:   # 24h of 1-second snapshots max
        self._follower_count: dict[str, int] = {}                # platform -> count
        self._new_follows: dict[str, list[str]] = defaultdict(list)
        self._unfollows: dict[str, list[str]] = defaultdict(list)
        self._peak_count: dict[str, int] = {}
        self._snapshots: dict[str, deque[FanSnapshot]] = defaultdict(
            lambda: deque(maxlen=3600)  # 1 hour at 1/sec
        )
        self._hourly_reports: dict[str, list[HourlyReport]] = defaultdict(list)
        self._daily_reports: dict[str, dict[str, DailyReport]] = defaultdict(dict)
        self._started_at: float = time.time()
        self._last_hour_report: float = 0.0
        # Hourly bucket tracking
        self._hourly_buckets: dict[str, dict[int, dict[str, int]]] = defaultdict(
            lambda: defaultdict(lambda: {"new": 0, "unfollow": 0, "start": 0})
        )

    def update(
        self, username: str, event_type: str, follower_count: int,
        platform: str = "unknown",
    ) -> FanSnapshot | None:
        """Record a follow/unfollow event or count update."""
        now = time.time()
        hour_key = int(now // 3600)

        prev_count = self._follower_count.get(platform, follower_count)

        new_follows = 0
        unfollows = 0

        if event_type == "follow":
            if username not in self._new_follows[platform]:
                self._new_follows[platform].append(username)
                new_follows = 1
            self._follower_count[platform] = prev_count + 1
        elif event_type == "unfollow":
            if username not in self._unfollows[platform]:
                self._unfollows[platform].append(username)
                unfollows = 1
            self._follower_count[platform] = max(0, prev_count - 1)
        else:
            # Direct count update from platform
            diff = follower_count - prev_count
            if diff > 0:
                new_follows = diff
            elif diff < 0:
                unfollows = abs(diff)
            self._follower_count[platform] = follower_count

        # Update peak
        current = self._follower_count[platform]
        if current > self._peak_count.get(platform, 0):
            self._peak_count[platform] = current

        # Track hourly bucket
        bucket = self._hourly_buckets[platform][hour_key]
        if bucket["start"] == 0:
            bucket["start"] = prev_count
        bucket["new"] += new_follows
        bucket["unfollow"] += unfollows

        snapshot = FanSnapshot(
            timestamp=now,
            platform=platform,
            follower_count=current,
            new_follows=new_follows,
            unfollows=unfollows,
        )
        self._snapshots[platform].append(snapshot)

        # Hourly report trigger
        if now - self._last_hour_report > 3600:
            self._generate_hourly_reports(now)
            self._last_hour_report = now

        return snapshot

    def _generate_hourly_reports(self, now: float) -> None:
        """Generate hourly reports for all platforms."""
        for platform, buckets in self._hourly_buckets.items():
            # Find completed hours
            current_hour = int(now // 3600)
            for hour_key in sorted(buckets.keys()):
                if hour_key >= current_hour:
                    continue
                b = buckets[hour_key]
                start = b["start"]
                end = start + b["new"] - b["unfollow"]

                report = HourlyReport(
                    hour_start=hour_key * 3600,
                    platform=platform,
                    start_count=start,
                    end_count=end,
                    new_follows=b["new"],
                    unfollows=b["unfollow"],
                    net_growth=b["new"] - b["unfollow"],
                )
                self._hourly_reports[platform].append(report)
                del buckets[hour_key]

        # Limit history
        for platform in self._hourly_reports:
            if len(self._hourly_reports[platform]) > 168:  # 7 days
                self._hourly_reports[platform] = self._hourly_reports[platform][-168:]

    def get_snapshot(self, platform: str = "unknown") -> FanSnapshot | None:
        """Get the most recent snapshot for a platform."""
        snaps = self._snapshots.get(platform)
        if snaps:
            return snaps[-1]
        return None

    def get_current_count(self, platform: str = "unknown") -> int:
        return self._follower_count.get(platform, 0)

    def get_peak_count(self, platform: str = "unknown") -> int:
        return self._peak_count.get(platform, 0)

    def get_hourly_reports(
        self, platform: str = "unknown", hours: int = 24
    ) -> list[HourlyReport]:
        return self._hourly_reports.get(platform, [])[-hours:]

    def get_trend_data(
        self, platform: str = "unknown", count: int = 100
    ) -> list[dict]:
        """Get trend data for visualization."""
        snaps = list(self._snapshots.get(platform, deque()))
        # Sample to requested count
        if len(snaps) > count:
            step = len(snaps) // count
            snaps = snaps[::step][-count:]

        return [
            {
                "timestamp": s.timestamp,
                "follower_count": s.follower_count,
                "new_follows": s.new_follows,
                "unfollows": s.unfollows,
                "time_str": datetime.fromtimestamp(s.timestamp).strftime("%H:%M:%S"),
            }
            for s in snaps
        ]

    def generate_daily_report(self, platform: str = "unknown") -> DailyReport:
        """Generate a daily report for a platform."""
        today = datetime.now().strftime("%Y-%m-%d")
        reports = self.get_hourly_reports(platform, 24)

        if not reports:
            return DailyReport(
                date=today,
                platform=platform,
                start_count=self._follower_count.get(platform, 0),
                end_count=self._follower_count.get(platform, 0),
                new_follows=0,
                unfollows=0,
                peak_count=self._peak_count.get(platform, 0),
            )

        first = reports[0]
        last = reports[-1]
        return DailyReport(
            date=today,
            platform=platform,
            start_count=first.start_count,
            end_count=last.end_count,
            new_follows=sum(r.new_follows for r in reports),
            unfollows=sum(r.unfollows for r in reports),
            peak_count=self._peak_count.get(platform, 0),
            hourly_reports=reports,
        )

    def get_stats(self) -> dict:
        result: dict = {}
        for platform in self._follower_count:
            snapshot = self.get_snapshot(platform)
            result[platform] = {
                "current_followers": self._follower_count[platform],
                "peak_followers": self._peak_count.get(platform, 0),
                "total_new_today": len(self._new_follows.get(platform, [])),
                "total_unfollows_today": len(self._unfollows.get(platform, [])),
                "last_snapshot": snapshot.to_dict() if snapshot else None,
                "hourly_reports": [
                    h.to_dict() for h in self.get_hourly_reports(platform, 6)
                ],
            }
        return result
