"""语音合成模块。

职责:
  - 文本转语音 (Piper TTS)
  - 通过事件总线发布语音生成事件

依赖: core (EventBus, ConfigCenter)
被依赖: avatar, live, agents
"""

from src.tts.service import TTSService
from src.tts.models import TTSVoice, TTSOutput

__all__ = ["TTSService", "TTSVoice", "TTSOutput"]
