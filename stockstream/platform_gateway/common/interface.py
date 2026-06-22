"""Common abstract interface for all live platform connectors."""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections import deque
from typing import AsyncIterator, Optional

from stockstream.platform_gateway.common.models import (
    CommentEvent,
    FollowEvent,
    GiftEvent,
    LikeEvent,
    LiveEvent,
    LiveEventType,
    Platform,
    PlatformConfig,
    ViewerEvent,
)

logger = logging.getLogger(__name__)


# ── Abstract Connector ───────────────────────────────────────────

class BasePlatformConnector(ABC):
    """Abstract base for all live platform connectors.

    Each platform implements its own polling/push-based event collection
    but exposes the same set of async methods.
    """

    def __init__(self, config: PlatformConfig) -> None:
        self.config = config
        self._running = False
        self._connected = False
        self._event_queue: asyncio.Queue[LiveEvent] = asyncio.Queue(maxsize=500)
        self._reconnect_count = 0
        self._last_event_time: float = 0.0
        self._total_comments = 0
        self._total_likes = 0
        self._total_gifts = 0
        self._total_follows = 0

    # ── Lifecycle ─────────────────────────────────────────────

    async def start(self) -> bool:
        """Connect to platform and begin event collection."""
        if self._running:
            return True

        try:
            connected = await self._connect()
            if connected:
                self._running = True
                self._connected = True
                self._reconnect_count = 0
                logger.info("%s connected (room=%s)", self.platform_name, self.config.room_id)
                return True
        except Exception:
            logger.exception("%s initial connection failed", self.platform_name)

        # Start with reconnection loop
        self._running = True
        asyncio.create_task(self._reconnect_loop())
        return False

    async def stop(self) -> None:
        """Disconnect and stop event collection."""
        self._running = False
        try:
            await self._disconnect()
        except Exception:
            pass
        self._connected = False
        logger.info("%s stopped", self.platform_name)

    async def _reconnect_loop(self) -> None:
        """Persistent reconnection loop."""
        while self._running:
            if self._connected:
                await asyncio.sleep(1)
                continue

            if self._reconnect_count >= self.config.max_reconnect_attempts:
                logger.error("%s max reconnect attempts reached", self.platform_name)
                break

            await asyncio.sleep(self.config.reconnect_interval)
            try:
                self._reconnect_count += 1
                logger.info("%s reconnecting (attempt %d)...", self.platform_name, self._reconnect_count)
                if await self._connect():
                    self._connected = True
                    self._reconnect_count = 0
            except Exception:
                logger.exception("%s reconnect failed", self.platform_name)

    # ── Abstract methods ──────────────────────────────────────

    @abstractmethod
    async def _connect(self) -> bool:
        """Establish platform-specific connection. Return True on success."""
        ...

    @abstractmethod
    async def _disconnect(self) -> None:
        """Close connection and cleanup."""
        ...

    @abstractmethod
    async def _poll_events(self) -> list[LiveEvent]:
        """Poll the platform for new events. Called periodically."""
        ...

    # ── Event push (called by subclasses) ─────────────────────

    async def _push_event(self, event: LiveEvent) -> None:
        """Push an event into the internal queue."""
        if self._event_queue.full():
            try:
                self._event_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self._last_event_time = time.time()
        await self._event_queue.put(event)

        # Update counters
        if isinstance(event, CommentEvent):
            self._total_comments += 1
        elif isinstance(event, LikeEvent):
            self._total_likes += event.count
        elif isinstance(event, GiftEvent):
            self._total_gifts += event.gift_count
        elif isinstance(event, FollowEvent):
            self._total_follows += 1

    def _emit_error(self, message: str) -> None:
        """Emit a platform error event (non-async, for sync context)."""
        from stockstream.platform_gateway.common.models import BaseEvent
        evt = BaseEvent(
            platform=self.config.platform,
            event_type=LiveEventType.PLATFORM_ERROR,
            raw={"message": message},
        )
        if not self._event_queue.full():
            self._event_queue.put_nowait(evt)

    def _emit_connected(self) -> None:
        """Emit connected event."""
        from stockstream.platform_gateway.common.models import BaseEvent
        evt = BaseEvent(
            platform=self.config.platform,
            event_type=LiveEventType.PLATFORM_CONNECTED,
            raw={"room_id": self.config.room_id},
        )
        if not self._event_queue.full():
            self._event_queue.put_nowait(evt)

    def _emit_disconnected(self) -> None:
        """Emit disconnected event."""
        from stockstream.platform_gateway.common.models import BaseEvent
        evt = BaseEvent(
            platform=self.config.platform,
            event_type=LiveEventType.PLATFORM_DISCONNECTED,
            raw={"room_id": self.config.room_id},
        )
        if not self._event_queue.full():
            self._event_queue.put_nowait(evt)

    # ── Public API ────────────────────────────────────────────

    @property
    def platform_name(self) -> str:
        return self.config.platform.value

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def iter_events(self) -> AsyncIterator[LiveEvent]:
        """Async iterator over incoming events."""
        while self._running or not self._event_queue.empty():
            try:
                event = await asyncio.wait_for(self._event_queue.get(), timeout=1.0)
                yield event
            except asyncio.TimeoutError:
                if not self._running and self._event_queue.empty():
                    break

    # ── Unified API methods (match user requirement) ──────────

    async def get_comments(self) -> list[CommentEvent]:
        """Drain all pending comment events."""
        result: list[CommentEvent] = []
        while not self._event_queue.empty():
            try:
                evt = self._event_queue.get_nowait()
                if evt.event_type == LiveEventType.COMMENT:
                    result.append(evt)
            except asyncio.QueueEmpty:
                break
        return result

    async def get_gifts(self) -> list[GiftEvent]:
        """Drain all pending gift events."""
        result: list[GiftEvent] = []
        while not self._event_queue.empty():
            try:
                evt = self._event_queue.get_nowait()
                if evt.event_type == LiveEventType.GIFT:
                    result.append(evt)
            except asyncio.QueueEmpty:
                break
        return result

    async def get_likes(self) -> list[LikeEvent]:
        """Drain all pending like events."""
        result: list[LikeEvent] = []
        while not self._event_queue.empty():
            try:
                evt = self._event_queue.get_nowait()
                if evt.event_type == LiveEventType.LIKE:
                    result.append(evt)
            except asyncio.QueueEmpty:
                break
        return result

    async def get_viewers(self) -> int:
        """Get latest viewer count."""
        # Non-drain scan
        viewer_count = 0
        temp: list[LiveEvent] = []
        while not self._event_queue.empty():
            try:
                evt = self._event_queue.get_nowait()
                if evt.event_type == LiveEventType.VIEWER_COUNT:
                    viewer_count = evt.viewer_count
                else:
                    temp.append(evt)
            except asyncio.QueueEmpty:
                break
        # Put non-viewer events back
        for evt in temp:
            if not self._event_queue.full():
                self._event_queue.put_nowait(evt)
        return viewer_count

    async def get_followers(self) -> int:
        """Get latest follower count."""
        follower_count = 0
        temp: list[LiveEvent] = []
        while not self._event_queue.empty():
            try:
                evt = self._event_queue.get_nowait()
                if evt.event_type == LiveEventType.FOLLOW:
                    follower_count = evt.follower_count
                else:
                    temp.append(evt)
            except asyncio.QueueEmpty:
                break
        for evt in temp:
            if not self._event_queue.full():
                self._event_queue.put_nowait(evt)
        return follower_count

    async def send_message(self, message: str) -> bool:
        """Send a chat message to the live room. Override per platform."""
        logger.debug("[%s] send_message not implemented: %s", self.platform_name, message[:50])
        return False

    async def start_live(self) -> bool:
        """Start a live stream on this platform. Override per platform."""
        logger.warning("[%s] start_live not implemented", self.platform_name)
        return False

    async def stop_live(self) -> bool:
        """Stop a live stream on this platform. Override per platform."""
        logger.warning("[%s] stop_live not implemented", self.platform_name)
        return False

    def get_stats(self) -> dict:
        return {
            "platform": self.platform_name,
            "connected": self._connected,
            "running": self._running,
            "total_comments": self._total_comments,
            "total_likes": self._total_likes,
            "total_gifts": self._total_gifts,
            "total_follows": self._total_follows,
            "reconnect_count": self._reconnect_count,
            "queue_size": self._event_queue.qsize(),
        }


# ── Gateway ─────────────────────────────────────────────────────

class LivePlatformGateway:
    """Unified gateway managing all platform connectors.

    Usage::

        from stockstream.platform_gateway import LivePlatformGateway
        gw = LivePlatformGateway()
        gw.register(DouyinConnector(config))
        gw.register(KuaishouConnector(config))
        await gw.start_all()
        async for event in gw.events():
            process(event)
    """

    def __init__(self) -> None:
        self._connectors: dict[Platform, BasePlatformConnector] = {}
        self._running = False

    def register(self, connector: BasePlatformConnector) -> None:
        """Register a platform connector."""
        self._connectors[connector.config.platform] = connector
        logger.info("Registered platform: %s", connector.platform_name)

    def unregister(self, platform: Platform) -> None:
        """Remove a platform connector."""
        if platform in self._connectors:
            del self._connectors[platform]

    async def start_all(self) -> dict[Platform, bool]:
        """Start all registered connectors."""
        results = {}
        for plat, conn in self._connectors.items():
            if conn.config.enabled:
                results[plat] = await conn.start()
            else:
                results[plat] = False
        self._running = True
        return results

    async def stop_all(self) -> None:
        """Stop all connectors."""
        self._running = False
        for conn in self._connectors.values():
            await conn.stop()

    async def events(self) -> AsyncIterator[LiveEvent]:
        """Iterate over events from all platforms, merged."""
        async def _drain(conn: BasePlatformConnector, queue: asyncio.Queue):
            async for evt in conn.iter_events():
                await queue.put(evt)

        merged: asyncio.Queue[LiveEvent] = asyncio.Queue(maxsize=1000)
        tasks = [
            asyncio.create_task(_drain(conn, merged))
            for conn in self._connectors.values()
        ]

        while self._running or not merged.empty():
            try:
                event = await asyncio.wait_for(merged.get(), timeout=1.0)
                yield event
            except asyncio.TimeoutError:
                if not self._running:
                    break

        for task in tasks:
            task.cancel()

    def get_connector(self, platform: Platform) -> BasePlatformConnector | None:
        """Get a specific platform connector."""
        return self._connectors.get(platform)

    def get_all_stats(self) -> dict:
        """Get aggregate stats for all platforms."""
        return {
            plat.value: conn.get_stats()
            for plat, conn in self._connectors.items()
        }
