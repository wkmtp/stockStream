"""TTS module — Piper-based local neural text-to-speech for live stock commentary.

Exports::

    from stockstream.tts import (
        TTSService,      # Main service — queue-based synthesis
        PiperEngine,     # Low-level Piper wrapper
        TTSTask,         # Synthesis task handle
        TTSPlayEvent,    # Per-sentence playback event
        TTSVoice,        # Voice configuration
        Sentence,        # Sentence fragment
        split_sentences, # Text → sentences utility
    )
"""

from stockstream.tts.engine import PiperEngine
from stockstream.tts.models import (
    Sentence,
    TTSPlayEvent,
    TTSStatus,
    TTSTask,
    TTSVoice,
)
from stockstream.tts.service import TTSService
from stockstream.tts.splitter import split_sentences

__all__ = [
    "PiperEngine",
    "Sentence",
    "split_sentences",
    "TTSPlayEvent",
    "TTSStatus",
    "TTSTask",
    "TTSService",
    "TTSVoice",
]
