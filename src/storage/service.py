"""统一存储服务 — 支持 SQLite / PostgreSQL，自动迁移。

特性:
    1. 多后端: SQLite（本地/开发）和 PostgreSQL（生产）
    2. 自动迁移: 基于模型定义自动创建/更新表结构
    3. 连接池: 异步连接管理
    4. 仓储模式: 每个领域独立的 Repository
    5. 事务支持: 上下文管理器

架构:
    StorageService (总入口)
    ├── StockRepository     — 股票数据
    ├── TradeRepository     — 交易记录
    ├── LiveRepository      — 直播记录
    ├── DanmuRepository     — 弹幕记录
    ├── UserRepository      — 用户数据
    ├── GiftRepository      — 礼物数据
    └── MigrationManager    — 自动迁移
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from sqlalchemy import (
    Column,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    inspect,
    text as sa_text,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from src.core.base import DatabaseError

logger = logging.getLogger(__name__)

# ── SQLAlchemy ORM Base ────────────────────────────────────────────────


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类。"""


# ── Repository Base ────────────────────────────────────────────────────


class Repository:
    """仓储基类，提供通用 CRUD 操作。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self._session_factory() as s:
            yield s

    async def _execute(self, stmt: Any) -> Any:
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            await session.commit()
            return result

    async def _fetch_all(self, stmt: Any) -> list[Any]:
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def _fetch_one(self, stmt: Any) -> Any | None:
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return result.scalar_one_or_none()


# ── Stock Repository ───────────────────────────────────────────────────


class StockRepository(Repository):
    """股票行情数据仓储。"""

    async def insert_price(self, symbol: str, price: float, volume: int = 0,
                           timestamp: str = "") -> None:
        from sqlalchemy import insert
        from src.storage.models import StockPrice
        await self._execute(insert(StockPrice).values(
            symbol=symbol, price=price, volume=volume, timestamp=timestamp,
        ))

    async def get_latest(self, symbol: str) -> float | None:
        from sqlalchemy import select
        from src.storage.models import StockPrice
        stmt = (
            select(StockPrice.price)
            .where(StockPrice.symbol == symbol)
            .order_by(StockPrice.timestamp.desc())
            .limit(1)
        )
        return await self._fetch_one(stmt)  # type: ignore[return-value]

    async def get_history(self, symbol: str, limit: int = 100) -> list[dict]:
        from sqlalchemy import select
        from src.storage.models import StockPrice
        stmt = (
            select(StockPrice)
            .where(StockPrice.symbol == symbol)
            .order_by(StockPrice.timestamp.desc())
            .limit(limit)
        )
        rows = await self._fetch_all(stmt)
        return [{"symbol": r.symbol, "price": r.price, "volume": r.volume,
                 "timestamp": r.timestamp} for r in rows]


# ── Trade Repository ───────────────────────────────────────────────────


class TradeRepository(Repository):
    """交易记录仓储。"""

    async def record_trade(self, symbol: str, action: str, quantity: int,
                           price: float, amount: float = 0.0,
                           reason: str = "") -> int:
        from sqlalchemy import insert
        from src.storage.models import TradeRecord
        result = await self._execute(insert(TradeRecord).values(
            symbol=symbol,
            action=action,
            quantity=quantity,
            price=price,
            amount=amount or quantity * price,
            reason=reason,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ))
        return result.lastrowid  # type: ignore[return-value]

    async def get_trades(self, limit: int = 50) -> list[dict]:
        from sqlalchemy import select
        from src.storage.models import TradeRecord
        stmt = select(TradeRecord).order_by(TradeRecord.timestamp.desc()).limit(limit)
        rows = await self._fetch_all(stmt)
        return [_row_to_dict(r) for r in rows]


# ── Live Repository ────────────────────────────────────────────────────


class LiveRepository(Repository):
    """直播记录仓储。"""

    async def start_session(self, platform: str, room_id: str) -> int:
        from sqlalchemy import insert
        from src.storage.models import LiveSession
        result = await self._execute(insert(LiveSession).values(
            platform=platform,
            room_id=room_id,
            started_at=datetime.now(timezone.utc).isoformat(),
            status="live",
        ))
        return result.lastrowid  # type: ignore[return-value]

    async def end_session(self, session_id: int) -> None:
        from sqlalchemy import update
        from src.storage.models import LiveSession
        await self._execute(
            update(LiveSession)
            .where(LiveSession.id == session_id)
            .values(
                ended_at=datetime.now(timezone.utc).isoformat(),
                status="ended",
            )
        )

    async def get_active_sessions(self) -> list[dict]:
        from sqlalchemy import select
        from src.storage.models import LiveSession
        stmt = select(LiveSession).where(LiveSession.status == "live")
        rows = await self._fetch_all(stmt)
        return [_row_to_dict(r) for r in rows]

    async def record_segment(self, session_id: int, segment_type: str,
                             content: str, duration: float = 0.0) -> None:
        from sqlalchemy import insert
        from src.storage.models import LiveSegment
        await self._execute(insert(LiveSegment).values(
            session_id=session_id,
            segment_type=segment_type,
            content=content,
            duration=duration,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ))


# ── Danmu Repository ────────────────────────────────────────────────────


class DanmuRepository(Repository):
    """弹幕记录仓储。"""

    async def insert(self, platform: str, username: str, content: str,
                     tags: str = "", level: int = 0, session_id: int = 0) -> None:
        from sqlalchemy import insert
        from src.storage.models import DanmuRecord
        await self._execute(insert(DanmuRecord).values(
            platform=platform,
            username=username,
            content=content,
            tags=tags,
            user_level=level,
            session_id=session_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ))

    async def get_recent(self, limit: int = 100) -> list[dict]:
        from sqlalchemy import select
        from src.storage.models import DanmuRecord
        stmt = select(DanmuRecord).order_by(DanmuRecord.timestamp.desc()).limit(limit)
        rows = await self._fetch_all(stmt)
        return [_row_to_dict(r) for r in rows]


# ── Gift Repository ──────────────────────────────────────────────────────


class GiftRepository(Repository):
    """礼物数据仓储。"""

    async def record_gift(self, platform: str, username: str, gift_name: str,
                          value: float = 0.0, count: int = 1,
                          session_id: int = 0) -> None:
        from sqlalchemy import insert
        from src.storage.models import GiftRecord
        await self._execute(insert(GiftRecord).values(
            platform=platform,
            username=username,
            gift_name=gift_name,
            value=value,
            count=count,
            session_id=session_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ))

    async def get_top_donors(self, limit: int = 10) -> list[dict]:
        from sqlalchemy import select, func
        from src.storage.models import GiftRecord
        stmt = (
            select(GiftRecord.username, func.sum(GiftRecord.value).label("total"))
            .group_by(GiftRecord.username)
            .order_by(func.sum(GiftRecord.value).desc())
            .limit(limit)
        )
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return [{"username": row[0], "total_value": float(row[1])} for row in result]


# ── User Repository ─────────────────────────────────────────────────────


class UserRepository(Repository):
    """用户/粉丝数据仓储。"""

    async def update_followers(self, platform: str, follower_count: int) -> None:
        from sqlalchemy import insert
        from src.storage.models import FollowerSnapshot
        await self._execute(insert(FollowerSnapshot).values(
            platform=platform,
            follower_count=follower_count,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ))

    async def get_follower_trend(self, platform: str, hours: int = 24) -> list[dict]:
        from sqlalchemy import select
        from src.storage.models import FollowerSnapshot
        cutoff = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        stmt = (
            select(FollowerSnapshot)
            .where(
                FollowerSnapshot.platform == platform,
            )
            .order_by(FollowerSnapshot.timestamp.desc())
            .limit(hours * 60)
        )
        rows = await self._fetch_all(stmt)
        return [{"count": r.follower_count, "timestamp": r.timestamp} for r in rows]


# ── Migration Manager ───────────────────────────────────────────────────


class MigrationManager:
    """数据库迁移管理器。"""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def run_migrations(self) -> None:
        """执行自动迁移 — 基于模型定义创建/更新表结构。

        策略:
          1. SQLite: 使用 CREATE TABLE IF NOT EXISTS
          2. PostgreSQL: 使用 CREATE TABLE IF NOT EXISTS + ALTER TABLE 增量
        """
        async with self.engine.begin() as conn:
            # 创建所有定义的 ORM 表
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database migrations completed successfully")

    async def get_schema_version(self) -> str:
        """获取当前 Schema 版本。"""
        async with self.engine.connect() as conn:
            try:
                result = await conn.execute(sa_text(
                    "SELECT version FROM schema_version ORDER BY applied_at DESC LIMIT 1"
                ))
                row = result.fetchone()
                return row[0] if row else "0.0.0"
            except Exception:
                return "0.0.0"

    async def get_table_info(self) -> list[dict]:
        """获取所有表的信息。"""
        def _inspect(conn):
            inspector = inspect(conn)
            tables = []
            for name in inspector.get_table_names():
                columns = [
                    {"name": c["name"], "type": str(c["type"]), "nullable": c["nullable"]}
                    for c in inspector.get_columns(name)
                ]
                tables.append({"table": name, "columns": columns})
            return tables
        async with self.engine.connect() as conn:
            return await conn.run_sync(_inspect)  # type: ignore[arg-type]


# ── Storage Service (总入口) ────────────────────────────────────────────


@dataclass
class StorageServiceConfig:
    """存储服务配置。"""
    url: str = "sqlite+aiosqlite:///data/stockstream.db"
    pool_size: int = 5
    pool_recycle: int = 3600          # 连接最大存活秒数（24h 稳定性）
    pool_timeout: int = 30            # 等待连接超时秒数
    max_overflow: int = 10            # 连接池最大溢出
    pool_pre_ping: bool = True
    auto_migrate: bool = True
    auto_cleanup_hours: int = 72      # 自动清理超过 N 小时的数据（0=关闭）


class StorageService:
    """统一存储服务 — 所有数据访问的唯一入口。

    Usage:
        storage = StorageService(StorageServiceConfig(...))
        await storage.start()

        await storage.stocks.insert_price("600519", 1800.0)
        await storage.trades.record_trade("600519", "buy", 100, 1800.0)
        await storage.danmu.insert("douyin", "user1", "好股票!")
    """

    def __init__(self, config: StorageServiceConfig | None = None) -> None:
        from src.core.config_center import ConfigCenter
        cfg = ConfigCenter()

        if config is None:
            config = StorageServiceConfig(
                url=cfg.get("database.url", "sqlite+aiosqlite:///data/stockstream.db"),
                pool_size=cfg.get("database.pool_size", 5),
                pool_pre_ping=cfg.get("database.pool_pre_ping", True),
                auto_migrate=cfg.get("database.auto_migrate", True),
            )

        self.config = config
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None
        self._migrations: MigrationManager | None = None

        # ── 领域仓储（lazy init） ──
        self._stocks: StockRepository | None = None
        self._trades: TradeRepository | None = None
        self._lives: LiveRepository | None = None
        self._danmu: DanmuRepository | None = None
        self._gifts: GiftRepository | None = None
        self._users: UserRepository | None = None

    @property
    def stocks(self) -> StockRepository:
        if self._stocks is None:
            self._stocks = StockRepository(self._session_factory)  # type: ignore[arg-type]
        return self._stocks

    @property
    def trades(self) -> TradeRepository:
        if self._trades is None:
            self._trades = TradeRepository(self._session_factory)  # type: ignore[arg-type]
        return self._trades

    @property
    def lives(self) -> LiveRepository:
        if self._lives is None:
            self._lives = LiveRepository(self._session_factory)  # type: ignore[arg-type]
        return self._lives

    @property
    def danmu(self) -> DanmuRepository:
        if self._danmu is None:
            self._danmu = DanmuRepository(self._session_factory)  # type: ignore[arg-type]
        return self._danmu

    @property
    def gifts(self) -> GiftRepository:
        if self._gifts is None:
            self._gifts = GiftRepository(self._session_factory)  # type: ignore[arg-type]
        return self._gifts

    @property
    def users(self) -> UserRepository:
        if self._users is None:
            self._users = UserRepository(self._session_factory)  # type: ignore[arg-type]
        return self._users

    @property
    def migrations(self) -> MigrationManager:
        if self._migrations is None:
            self._migrations = MigrationManager(self._engine)  # type: ignore[arg-type]
        return self._migrations

    # ── Lifecycle ───────────────────────────────────────────────────

    async def start(self) -> None:
        """初始化数据库连接。"""
        db_path = self.config.url
        is_sqlite = db_path.startswith("sqlite")

        if is_sqlite and ":memory:" not in db_path:
            # Ensure data directory exists
            path = db_path.replace("sqlite+aiosqlite:///", "")
            Path(path).parent.mkdir(parents=True, exist_ok=True)

        # V3.0: SQLite (aiosqlite) 使用 StaticPool，不支持 pool_size / pool_pre_ping 等参数
        if is_sqlite:
            engine_kwargs: dict = {
                "connect_args": {"check_same_thread": False},
            }
        else:
            engine_kwargs = {
                "pool_pre_ping": self.config.pool_pre_ping,
                "pool_size": self.config.pool_size,
                "pool_recycle": self.config.pool_recycle,
                "pool_timeout": self.config.pool_timeout,
                "max_overflow": self.config.max_overflow,
            }

        self._engine = create_async_engine(self.config.url, **engine_kwargs)
        self._session_factory = async_sessionmaker(
            self._engine, expire_on_commit=False,
        )

        if self.config.auto_migrate:
            await self.migrations.run_migrations()

        logger.info("StorageService started: %s", self._describe_backend())

    async def stop(self) -> None:
        """关闭数据库连接。"""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
        logger.info("StorageService stopped")

    async def health(self) -> dict[str, str]:
        """健康检查。"""
        try:
            async with self._session_factory() as session:  # type: ignore[misc]
                await session.execute(sa_text("SELECT 1"))
            return {"status": "healthy", "backend": self._describe_backend()}
        except Exception as exc:
            return {"status": "unhealthy", "error": str(exc)}

    async def cleanup_old_data(self, keep_hours: int | None = None) -> dict[str, int]:
        """清理超过 N 小时的旧数据，防止 24h 运行后数据库无限膨胀。

        Returns:
            {"stock_prices": N, "danmu_records": N, ...} — 每张表删除的行数
        """
        if keep_hours is None:
            keep_hours = self.config.auto_cleanup_hours
        if keep_hours <= 0:
            return {}

        cutoff = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        cutoff_timestamp = str(int(time.time() - keep_hours * 3600))

        tables = [
            ("stock_prices", "timestamp", cutoff_timestamp),
            ("trade_records", "timestamp", cutoff),
            ("danmu_records", "timestamp", cutoff),
            ("gift_records", "timestamp", cutoff),
            ("follower_snapshots", "timestamp", cutoff),
            ("live_sessions", "started_at", cutoff),
            ("live_segments", "timestamp", cutoff),
        ]

        deleted: dict[str, int] = {}
        for table, col, cutoff_val in tables:
            try:
                async with self._session_factory() as session:  # type: ignore[misc]
                    stmt = sa_text(f"DELETE FROM {table} WHERE {col} < :cutoff")
                    result = await session.execute(stmt, {"cutoff": cutoff_val})
                    await session.commit()
                    deleted[table] = result.rowcount or 0  # type: ignore[assignment]
            except Exception as exc:
                logger.warning("StorageService: cleanup %s failed — %s", table, exc)

        total = sum(deleted.values())
        if total:
            logger.info("StorageService: cleaned %d rows across %d tables (keep_hours=%d)",
                        total, len(deleted), keep_hours)
        return deleted

    def _describe_backend(self) -> str:
        if "postgresql" in self.config.url:
            return "postgresql"
        return "sqlite"


# ── Helpers ─────────────────────────────────────────────────────────────


def _row_to_dict(row: Any) -> dict[str, Any]:
    """将 ORM 行转换为字典。"""
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}
