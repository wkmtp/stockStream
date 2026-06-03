"""Application settings tuned for single-node Jetson deployment."""

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(env_prefix="STOCKSTREAM_", env_file=".env")

    host: str = "0.0.0.0"
    port: int = 8000
    db_url: str = "sqlite+aiosqlite:///data/stockstream.db"
    max_memory_mb: int = Field(default=6144, ge=512, le=6144)
    tensorrt_enabled: bool = False
    stream_queue_size: int = Field(default=1024, ge=128, le=8192)
    market_poll_seconds: int = Field(default=5, ge=1, le=300)
    market_sqlite_path: str = "data/market_cache.db"
    market_symbols: str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance to avoid repeated parsing."""

    return Settings()
