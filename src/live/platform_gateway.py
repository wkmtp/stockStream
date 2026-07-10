"""直播平台统一网关 — 抖音/快手/B站/视频号 抽象层。"""
from __future__ import annotations
import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


class Platform(Enum):
    DOUYIN = "douyin"
    KUAISHOU = "kuaishou"
    BILIBILI = "bilibili"
    WECHAT = "wechat"


class ConnectorState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class PlatformStats:
    platform: str
    state: ConnectorState = ConnectorState.DISCONNECTED
    viewers: int = 0
    likes: int = 0
    gifts: int = 0
    comments: int = 0
    followers: int = 0
    errors: int = 0

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "state": self.state.value,
            "viewers": self.viewers,
            "likes": self.likes,
            "gifts": self.gifts,
            "comments": self.comments,
            "followers": self.followers,
        }


class BaseConnector(ABC):
    """平台连接器抽象基类。"""

    @abstractmethod
    async def connect(self) -> bool: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def send_message(self, text: str) -> bool: ...

    @abstractmethod
    async def get_stats(self) -> PlatformStats: ...


class LivePlatformGateway:
    """直播平台总控网关。

    统一管理所有直播平台的连接和数据流。
    所有平台事件统一推送到事件总线。
    """

    def __init__(self, bus: EventBus | None = None) -> None:
        self._bus: EventBus | None = bus
        self._connectors: dict[Platform, BaseConnector] = {}
        self._stats: dict[Platform, PlatformStats] = {}
        self._running = False

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    def register(self, platform: Platform, connector: BaseConnector) -> None:
        self._connectors[platform] = connector
        self._stats[platform] = PlatformStats(platform=platform.value)
        logger.info("Registered connector: %s", platform.value)

    async def start(self, platform: Platform | None = None) -> bool:
        """启动指定平台（或全部）。"""
        targets = [platform] if platform else list(self._connectors.keys())
        ok = True
        for p in targets:
            conn = self._connectors.get(p)
            if conn:
                try:
                    if await conn.connect():
                        self._stats[p].state = ConnectorState.CONNECTED
                        bus = await self.bus
                        await bus.emit_async("live.platform_connected", {
                            "platform": p.value,
                        })
                    else:
                        ok = False
                except Exception as exc:
                    self._stats[p].state = ConnectorState.ERROR
                    self._stats[p].errors += 1
                    logger.error("Platform %s connect failed: %s", p.value, exc)
                    ok = False
        return ok

    async def stop(self, platform: Platform | None = None) -> None:
        targets = [platform] if platform else list(self._connectors.keys())
        for p in targets:
            conn = self._connectors.get(p)
            if conn:
                await conn.disconnect()
                self._stats[p].state = ConnectorState.DISCONNECTED

    async def broadcast(self, text: str) -> None:
        """向所有已连接平台发送消息。"""
        for p, conn in self._connectors.items():
            if self._stats[p].state == ConnectorState.CONNECTED:
                await conn.send_message(text)

    def get_all_stats(self) -> dict:
        return {p.value: s.to_dict() for p, s in self._stats.items()}
