"""In-memory stream bus with bounded queues to protect Jetson memory."""

import asyncio
from stockstream.core.config import get_settings


class StreamService:
    """Small pub/sub bus for ticks, selections, agent events, and danmu."""

    def __init__(self) -> None:
        settings = get_settings()
        self.queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=settings.stream_queue_size)

    async def publish(self, event: dict) -> None:
        """Publish an event, dropping the oldest event when the queue is full."""

        if self.queue.full():
            _ = self.queue.get_nowait()
        await self.queue.put(event)

    async def next_event(self) -> dict:
        """Wait for and return the next event."""

        return await self.queue.get()
