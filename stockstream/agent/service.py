"""Decision agent module coordinating selector and TTS outputs."""

from stockstream.selector.service import SelectorService
from stockstream.tts.service import TTSService


class AgentService:
    """Lightweight strategy assistant facade."""

    def __init__(self, selector: SelectorService, tts: TTSService) -> None:
        self.selector = selector
        self.tts = tts

    async def brief(self, symbols: list[str]) -> dict:
        """Generate a compact market brief for ranked symbols."""

        rankings = await self.selector.rank(symbols)
        message = "关注: " + ", ".join(item["symbol"] for item in rankings[:3])
        speech = await self.tts.speak(message)
        return {"rankings": rankings, "speech": speech}
