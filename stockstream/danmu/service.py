"""Danmu/bullet-comment module for live stream overlays."""

from stockstream.stream.service import StreamService


class DanmuService:
    """Publishes bounded danmu events to the stream bus."""

    def __init__(self, stream: StreamService) -> None:
        self.stream = stream

    async def send(self, message: str) -> dict:
        """Publish a danmu message."""

        event = {"type": "danmu.message", "message": message[:120]}
        await self.stream.publish(event)
        return event
