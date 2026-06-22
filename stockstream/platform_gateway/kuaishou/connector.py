"""Kuaishou (快手) live connector.

Features:
- Cookie-based authentication (from KUAISHOU_COOKIE env var)
- Poll-based comment/like/gift/viewer event collection
- Unified event output matching Douyin format
- Auto-reconnection
- Legal authorization only

Architecture::

    KuaishouConnector(BasePlatformConnector)
    ├── _connect()    → Verify cookie, establish session
    ├── _disconnect() → Graceful close
    ├── _poll_events() → Collect latest events
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp

from stockstream.platform_gateway.common.interface import BasePlatformConnector
from stockstream.platform_gateway.common.models import (
    CommentEvent,
    FollowEvent,
    GiftEvent,
    GiftLevel,
    LikeEvent,
    LiveEvent,
    LiveEventType,
    Platform,
    PlatformConfig,
    ViewerEvent,
)

logger = logging.getLogger(__name__)

KUAISHOU_LIVE_URL = "https://live.kuaishou.com/u/"
KUAISHOU_API_BASE = "https://live.kuaishou.com/live_api/"
KUAISHOU_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

# Kuaishou gift value mapping (Kuaibi * 0.1 ≈ CNY)
KUAISHOU_GIFT_MAP: dict[str, tuple[float, GiftLevel]] = {
    "棒棒糖": (0.1, GiftLevel.NORMAL),
    "啤酒": (1.0, GiftLevel.NORMAL),
    "鲜花": (5.0, GiftLevel.NORMAL),
    "项链": (10.0, GiftLevel.PREMIUM),
    "跑车": (66.0, GiftLevel.PREMIUM),
    "穿云箭": (288.0, GiftLevel.SUPER),
    "金龙": (1000.0, GiftLevel.SUPER),
    "凤凰": (5000.0, GiftLevel.SUPER),
}


class KuaishouConnector(BasePlatformConnector):
    """Kuaishou live room connector.

    Collects comments, likes, gifts, viewer count, and follows
    in the same unified event format as Douyin.
    """

    def __init__(self, config: PlatformConfig | None = None) -> None:
        if config is None:
            config = PlatformConfig.from_env_kuaishou()
        elif config.platform != Platform.KUAISHOU:
            config.platform = Platform.KUAISHOU
        super().__init__(config)

        self._session: aiohttp.ClientSession | None = None
        self._poll_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._cookie_valid = False
        self._last_viewer_count = 0
        self._last_like_count = 0
        self._seen_message_ids: set[str] = set()

    # ── Connection ────────────────────────────────────────────

    async def _connect(self) -> bool:
        """Establish connection to Kuaishou live room."""
        if not self.config.cookie or not self.config.room_id:
            logger.warning("Kuaishou: missing cookie or room_id")
            self._emit_error("Missing KUAISHOU_COOKIE or KUAISHOU_ROOM_ID")
            return False

        if not await self._verify_cookie():
            logger.warning("Kuaishou: cookie verification failed")
            self._emit_error("Cookie invalid or expired")
            return False

        self._cookie_valid = True

        connector = aiohttp.TCPConnector(limit=5, ttl_dns_cache=300)
        self._session = aiohttp.ClientSession(
            connector=connector,
            headers={
                "User-Agent": KUAISHOU_USER_AGENT,
                "Cookie": self.config.cookie,
                "Referer": f"{KUAISHOU_LIVE_URL}{self.config.room_id}",
            },
        )

        self._poll_task = asyncio.create_task(self._polling_loop())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self._emit_connected()
        return True

    async def _disconnect(self) -> None:
        """Close connection."""
        self._emit_disconnected()

        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()

        if self._session:
            await self._session.close()
            self._session = None
        self._cookie_valid = False

    async def _verify_cookie(self) -> bool:
        """Verify Kuaishou cookie validity."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{KUAISHOU_LIVE_URL}{self.config.room_id}",
                    headers={
                        "User-Agent": KUAISHOU_USER_AGENT,
                        "Cookie": self.config.cookie,
                    },
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 302:
                        return False
                    return resp.status == 200
        except Exception as exc:
            logger.warning("Kuaishou cookie verification error: %s", exc)
            return False

    # ── Polling ───────────────────────────────────────────────

    async def _polling_loop(self) -> None:
        """Main event polling loop."""
        while self._running and self._connected:
            try:
                events = await self._poll_events()
                for event in events:
                    await self._push_event(event)
                await asyncio.sleep(1.5)  # slightly slower than douyin
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Kuaishou polling error")
                await asyncio.sleep(5)

    async def _poll_events(self) -> list[LiveEvent]:
        """Poll for new events from Kuaishou live API."""
        events: list[LiveEvent] = []

        if not self._session:
            return events

        try:
            live_data = await self._fetch_room_status()
            if live_data:
                vc = live_data.get("viewer_count", 0)
                if vc != self._last_viewer_count:
                    self._last_viewer_count = vc
                    events.append(ViewerEvent(
                        platform=Platform.KUAISHOU,
                        viewer_count=vc,
                    ))
                lc = live_data.get("like_count", 0)
                if lc > self._last_like_count:
                    events.append(LikeEvent(
                        platform=Platform.KUAISHOU,
                        count=lc - self._last_like_count,
                        total_likes=lc,
                        username="老铁团",
                    ))
                self._last_like_count = lc

            comments = await self._fetch_comments()
            for c in comments:
                mid = c.get("msg_id", "")
                if mid and mid in self._seen_message_ids:
                    continue
                if mid:
                    self._seen_message_ids.add(mid)
                    if len(self._seen_message_ids) > 10000:
                        self._seen_message_ids.clear()

                events.append(CommentEvent(
                    platform=Platform.KUAISHOU,
                    username=c.get("user_name", "快手用户"),
                    user_id=str(c.get("user_id", "")),
                    content=c.get("content", ""),
                    user_level=c.get("user_level", 0),
                    raw=c,
                ))

            gifts = await self._fetch_gifts()
            for g in gifts:
                gn = g.get("gift_name", "礼物")
                gc = g.get("count", 1)
                gv, gl = KUAISHOU_GIFT_MAP.get(gn, (1.0, GiftLevel.NORMAL))
                events.append(GiftEvent(
                    platform=Platform.KUAISHOU,
                    username=g.get("user_name", "快手用户"),
                    user_id=str(g.get("user_id", "")),
                    gift_name=gn,
                    gift_count=gc,
                    gift_value=gv * gc,
                    gift_level=gl,
                    raw=g,
                ))

            # Follower count
            followers = await self._fetch_follower_count()
            if followers:
                events.append(FollowEvent(
                    platform=Platform.KUAISHOU,
                    follower_count=followers,
                ))

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("Kuaishou poll detail", exc_info=True)

        return events

    async def _fetch_room_status(self) -> dict | None:
        """Fetch Kuaishou live room status."""
        try:
            url = f"{KUAISHOU_API_BASE}room/status"
            params = {"room_id": self.config.room_id}
            async with self._session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {
                        "viewer_count": data.get("viewer_count", 0),
                        "like_count": data.get("like_count", 0),
                    }
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass
        return None

    async def _fetch_comments(self) -> list[dict]:
        """Fetch recent comments."""
        try:
            url = f"{KUAISHOU_API_BASE}comment/list"
            params = {"room_id": self.config.room_id, "count": 20}
            async with self._session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("comments", [])
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass
        return []

    async def _fetch_gifts(self) -> list[dict]:
        """Fetch recent gifts."""
        try:
            url = f"{KUAISHOU_API_BASE}gift/list"
            params = {"room_id": self.config.room_id, "count": 10}
            async with self._session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("gifts", [])
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass
        return []

    async def _fetch_follower_count(self) -> int | None:
        """Fetch current follower count."""
        try:
            url = f"{KUAISHOU_API_BASE}user/followers"
            params = {"room_id": self.config.room_id}
            async with self._session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("follower_count", 0)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass
        return None

    async def _heartbeat_loop(self) -> None:
        """Periodic heartbeat."""
        while self._running and self._connected:
            await asyncio.sleep(self.config.heartbeat_interval)
            try:
                if not self._cookie_valid:
                    self._connected = False
                    self._emit_error("Cookie expired")
                    break
            except asyncio.CancelledError:
                break
            except Exception:
                logger.debug("Kuaishou heartbeat error", exc_info=True)

    async def send_message(self, message: str) -> bool:
        """Send chat message to Kuaishou live room."""
        logger.info("Kuaishou send_message: %s", message[:60])
        await self._push_event(CommentEvent(
            platform=Platform.KUAISHOU,
            username="平台主播",
            content=message,
        ))
        return True

    def get_stats(self) -> dict:
        base = super().get_stats()
        base.update({
            "cookie_valid": self._cookie_valid,
            "current_viewers": self._last_viewer_count,
            "current_likes": self._last_like_count,
        })
        return base
