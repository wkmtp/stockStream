"""TTS 模型定义。"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class TTSVoice:
    name: str = "zh_CN-huayan-medium"
    model_path: str = ""
    sample_rate: int = 22050
    length_scale: float = 1.0
    noise_scale: float = 0.667
    noise_w: float = 0.8
    sentence_silence: float = 0.2


@dataclass
class TTSOutput:
    """TTS 合成结果。"""
    text: str
    wav_path: str = ""
    duration: float = 0.0
    task_id: str = ""
    sentence_index: int = 0
    is_last: bool = False

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "wav_path": self.wav_path,
            "duration": self.duration,
            "task_id": self.task_id,
            "sentence_index": self.sentence_index,
            "is_last": self.is_last,
        }
