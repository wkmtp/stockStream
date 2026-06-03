"""SQLite database access layer for local single-node deployment."""

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from stockstream.core.config import get_settings


class DatabaseService:
    """Owns the async SQLAlchemy engine and session factory."""

    def __init__(self) -> None:
        settings = get_settings()
        self.engine: AsyncEngine = create_async_engine(settings.db_url, pool_pre_ping=True)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def health(self) -> dict[str, str]:
        """Return database health metadata."""

        return {"status": "ready", "backend": "sqlite"}

    async def close(self) -> None:
        """Dispose the engine on application shutdown."""

        await self.engine.dispose()
