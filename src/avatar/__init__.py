"""数字人渲染模块。

职责:
  - Wav2Lip 数字人嘴型同步
  - 视频渲染输出

依赖: core (EventBus), tts
被依赖: stream, live
"""

from src.avatar.service import AvatarService

__all__ = ["AvatarService"]
