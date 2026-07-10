"""TTS 语音合成服务。"""
from __future__ import annotations
import asyncio
import logging
import uuid
from src.core.event_bus import EventBus, get_event_bus
from src.tts.models import TTSVoice, TTSOutput

logger = logging.getLogger(__name__)


class TTSService:
    """语音合成服务。

    推送事件:
      tts.sentence_ready  — 单句合成完毕
      tts.task_complete   — 全部合成完毕
    """

    def __init__(
        self,
        voice: TTSVoice | None = None,
        bus: EventBus | None = None,
    ) -> None:
        self.voice = voice or TTSVoice()
        self._bus: EventBus | None = bus
        self._sentence_count = 0

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    async def synthesize(self, text: str) -> list[TTSOutput]:
        """将文本合成为语音（句子级别）。"""
        sentences = self._split_sentences(text)
        bus = await self.bus
        results = []
        task_id = uuid.uuid4().hex[:12]

        for i, sentence in enumerate(sentences):
            output = TTSOutput(
                text=sentence,
                wav_path=f"data/tts/{task_id}_{i}.wav",
                duration=len(sentence) * 0.25,
                task_id=task_id,
                sentence_index=i,
                is_last=(i == len(sentences) - 1),
            )
            results.append(output)

            await bus.emit_async("tts.sentence_ready", output.to_dict(), source="tts")

        await bus.emit_async("tts.task_complete", {
            "task_id": task_id,
            "sentences": len(sentences),
        }, source="tts")

        return results

    def _split_sentences(self, text: str) -> list[str]:
        """简单分句。"""
        import re
        parts = re.split(r"(?<=[。！？\n])", text)
        return [p.strip() for p in parts if p.strip()]
