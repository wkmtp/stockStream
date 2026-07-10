"""Application settings tuned for single-node Jetson deployment."""

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(env_prefix="STOCKSTREAM_", env_file=".env")

    host: str = "0.0.0.0"
    port: int = 8080
    db_url: str = "sqlite+aiosqlite:///data/stockstream.db"
    max_memory_mb: int = Field(default=6144, ge=512, le=6144)
    tensorrt_enabled: bool = False
    stream_queue_size: int = Field(default=1024, ge=128, le=8192)
    stream_rtmp_url: str = ""
    market_poll_seconds: int = Field(default=5, ge=1, le=300)
    market_sqlite_path: str = "data/market_cache.db"
    market_symbols: str = ""
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    deepseek_timeout: float = 30.0
    tts_voice: str = "zh_CN-huayan-medium"
    tts_model_path: str = "models/zh_CN-huayan-medium.onnx"
    tts_voice_male: str = "zh_CN-chaowen-medium"
    tts_model_path_male: str = "models/zh_CN-chaowen-medium.onnx"
    tts_voice_female: str = "zh_CN-huayan-medium"
    tts_model_path_female: str = "models/zh_CN-huayan-medium.onnx"
    tts_sample_rate: int = 22050
    tts_length_scale: float = 1.0
    tts_noise_scale: float = 0.667
    tts_noise_w: float = 0.8
    tts_sentence_silence: float = 0.2
    trader_capital: float = 3000.0
    trader_portfolio_path: str = "data/portfolio.json"
    trader_tick_seconds: float = 10.0
    trader_auto_open: bool = True
    trader_auto_add: bool = True
    trader_auto_reduce: bool = False
    trader_auto_clear: bool = True
    trader_report_dir: str = "data"
    avatar_enabled: bool = False
    avatar_host_image: str = "data/host.png"
    avatar_face_detector_onnx: str = "models/face_detector.onnx"
    avatar_wav2lip_onnx: str = "models/wav2lip_gan.onnx"
    avatar_fps: int = 25
    avatar_face_batch_size: int = 128
    avatar_output_dir: str = "data/avatar"
    avatar_auto_generate: bool = True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance to avoid repeated parsing."""

    return Settings()
