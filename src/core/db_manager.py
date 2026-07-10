"""Database Manager - unified database management.

V3.0 Production:
  - SQLite WAL mode (Write-Ahead Logging)
  - Connection pooling (avoid multi-thread contention)
  - Auto backup integration
  - Health check interface
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator, Generator

logger = logging.getLogger(__name__)


@dataclass
class DBConfig:
    db_path: str = "data/stockstream.db"
    wal_mode: bool = True
    journal_mode: str = "WAL"
    synchronous: str = "NORMAL"
    cache_size_kb: int = -64000
    busy_timeout_ms: int = 5000
    foreign_keys: bool = True
    pool_size: int = 4
    backup_enabled: bool = True
    backup_interval_hours: int = 24
    backup_retention_days: int = 30
    backup_dir: str = "backups/db"


class ConnectionPool:
    """Thread-safe SQLite connection pool."""

    def __init__(self, db_path: str, size: int = 4, timeout: float = 5.0) -> None:
        self._db_path = db_path
        self._size = size
        self._timeout = timeout
        self._pool: list[sqlite3.Connection] = []
        self._in_use: set[sqlite3.Connection] = set()
        self._lock = threading.Lock()
        self._semaphore = threading.Semaphore(size)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self._db_path,
            timeout=self._timeout,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def acquire(self) -> sqlite3.Connection:
        """获取连接（带异常安全保护，防止 semaphore 泄漏）。

        V3.0 生产级修复: 如果 _semaphore.acquire() 成功后 _create_connection()
        抛出异常，必须释放 semaphore 防止永久泄漏。
        """
        acquired = self._semaphore.acquire(timeout=self._timeout)
        if not acquired:
            raise TimeoutError(
                f"Database connection pool exhausted ({self._size}), "
                f"timed out after {self._timeout}s"
            )
        try:
            with self._lock:
                if self._pool:
                    conn = self._pool.pop()
                else:
                    conn = self._create_connection()
                self._in_use.add(conn)
            return conn
        except Exception:
            self._semaphore.release()
            raise

    def release(self, conn: sqlite3.Connection) -> None:
        try:
            with self._lock:
                if conn in self._in_use:
                    self._in_use.discard(conn)
                if len(self._pool) < self._size:
                    self._pool.append(conn)
                else:
                    try:
                        conn.close()
                    except Exception:
                        pass
        finally:
            self._semaphore.release()

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = self.acquire()
        try:
            yield conn
        finally:
            self.release(conn)

    def close_all(self) -> None:
        with self._lock:
            for conn in self._pool:
                try:
                    conn.close()
                except Exception:
                    pass
            self._pool.clear()
            for conn in list(self._in_use):
                try:
                    conn.close()
                except Exception:
                    pass
            self._in_use.clear()

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "pool_size": self._size,
                "available": len(self._pool),
                "in_use": len(self._in_use),
            }


class DatabaseManager:
    """V3.0: Unified database manager.

    Responsibilities:
      - Manage SQLite connection pool (WAL mode)
      - Provide safe context manager interface
      - Auto backup (daily at 3 AM)
      - Health check
    """

    def __init__(self, config: DBConfig | None = None) -> None:
        self._config = config or DBConfig()
        self._pool: ConnectionPool | None = None
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return
        db_path = self._config.db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._pool = ConnectionPool(
            db_path=db_path,
            size=self._config.pool_size,
            timeout=self._config.busy_timeout_ms / 1000.0,
        )
        with self._pool.connection() as conn:
            self._init_schema(conn)
        if self._config.wal_mode:
            with self._pool.connection() as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self._initialized = True
        logger.info("DatabaseManager initialized: %s (WAL=%s, pool=%d)",
                    db_path, self._config.wal_mode, self._config.pool_size)

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS system_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at REAL DEFAULT (strftime('%s', 'now'))
            );
            CREATE TABLE IF NOT EXISTS backup_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                backup_path TEXT NOT NULL,
                size_bytes INTEGER,
                created_at REAL DEFAULT (strftime('%s', 'now')),
                status TEXT DEFAULT 'success'
            );
            CREATE TABLE IF NOT EXISTS system_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                event_data TEXT,
                created_at REAL DEFAULT (strftime('%s', 'now'))
            );
            CREATE INDEX IF NOT EXISTS idx_system_events_type
                ON system_events(event_type);
            CREATE INDEX IF NOT EXISTS idx_system_events_time
                ON system_events(created_at);
            CREATE INDEX IF NOT EXISTS idx_backup_log_time
                ON backup_log(created_at);
        """)
        conn.commit()

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        if not self._initialized:
            self.initialize()
        assert self._pool is not None
        with self._pool.connection() as conn:
            yield conn

    def execute(self, sql: str, params: tuple | dict | None = None) -> sqlite3.Cursor:
        """Execute a single SQL statement (同步, 供 DatabaseManager 内部使用)。"""
        with self.get_connection() as conn:
            cursor = conn.execute(sql, params or ())
            conn.commit()
            return cursor

    async def execute_async(self, sql: str, params: tuple | dict | None = None) -> sqlite3.Cursor:
        """V3.0: 异步执行 SQL（线程池中运行，不阻塞事件循环）。"""
        return await asyncio.to_thread(self.execute, sql, params)

    async def query_async(self, sql: str, params: tuple | dict | None = None) -> list[dict[str, Any]]:
        """V3.0: 异步查询（线程池中运行）。"""
        return await asyncio.to_thread(self.query, sql, params)

    async def query_one_async(self, sql: str, params: tuple | dict | None = None) -> dict[str, Any] | None:
        """V3.0: 异步单行查询（线程池中运行）。"""
        return await asyncio.to_thread(self.query_one, sql, params)

    @asynccontextmanager
    async def get_connection_async(self) -> AsyncGenerator[sqlite3.Connection, None]:
        """V3.0: 异步获取数据库连接（线程池中运行）。"""
        if not self._initialized:
            await asyncio.to_thread(self.initialize)
        assert self._pool is not None
        conn = await asyncio.to_thread(self._pool.acquire)
        try:
            yield conn
        finally:
            await asyncio.to_thread(self._pool.release, conn)

    async def checkpoint_wal(self) -> None:
        """V3.0: 执行 WAL checkpoint 防止 WAL 文件无限增长。"""
        try:
            with self.get_connection() as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            logger.debug("WAL checkpoint completed")
        except Exception as exc:
            logger.warning("WAL checkpoint failed: %s", exc)

    async def integrity_check(self) -> dict[str, Any]:
        """V3.0: 执行数据库完整性检查，返回结果。"""
        try:
            with self.get_connection() as conn:
                row = conn.execute("PRAGMA integrity_check").fetchone()
                result = row[0] if row else "unknown"
                ok = result == "ok"
                if not ok:
                    logger.error("Database integrity check FAILED: %s", result)
            return {"status": "healthy" if ok else "corrupt", "detail": result}
        except Exception as exc:
            logger.error("Database integrity check error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    async def vacuum(self) -> None:
        """V3.0: 回收数据库空间（VACUUM 重建数据库文件）。"""
        try:
            with self.get_connection() as conn:
                conn.execute("VACUUM")
            logger.info("Database VACUUM completed")
        except Exception as exc:
            logger.warning("Database VACUUM failed: %s", exc)

    def execute_many(self, sql: str, params_list: list[tuple]) -> sqlite3.Cursor:
        """Execute multiple SQL statements in batch."""
        with self.get_connection() as conn:
            cursor = conn.executemany(sql, params_list)
            conn.commit()
            return cursor

    def query(self, sql: str, params: tuple | dict | None = None) -> list[dict]:
        """Query and return list of dicts."""
        with self.get_connection() as conn:
            cursor = conn.execute(sql, params or ())
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def query_one(self, sql: str, params: tuple | dict | None = None) -> dict | None:
        """Query single row."""
        with self.get_connection() as conn:
            cursor = conn.execute(sql, params or ())
            row = cursor.fetchone()
            return dict(row) if row else None

    def backup(self, backup_dir: str | None = None) -> str:
        """Backup database to specified directory."""
        backup_dir = backup_dir or self._config.backup_dir
        Path(backup_dir).mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_name = f"stockstream_{timestamp}.db"
        backup_path = os.path.join(backup_dir, backup_name)
        with self.get_connection() as src_conn:
            src_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            dst_conn = sqlite3.connect(backup_path)
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
        size_bytes = os.path.getsize(backup_path)
        logger.info("Database backup completed: %s (%.1f MB)", backup_path, size_bytes / 1024**2)
        self.execute(
            "INSERT INTO backup_log (backup_path, size_bytes, status) VALUES (?, ?, 'success')",
            (backup_path, size_bytes),
        )
        self._cleanup_old_backups(backup_dir)
        return backup_path

    def _cleanup_old_backups(self, backup_dir: str) -> None:
        retention_sec = self._config.backup_retention_days * 86400
        now = time.time()
        removed = 0
        for fname in os.listdir(backup_dir):
            if not fname.startswith("stockstream_") or not fname.endswith(".db"):
                continue
            fpath = os.path.join(backup_dir, fname)
            if now - os.path.getmtime(fpath) > retention_sec:
                try:
                    os.remove(fpath)
                    removed += 1
                except OSError:
                    pass
        if removed:
            logger.info("Cleaned up %d old database backups", removed)

    def health_check(self) -> dict:
        """Database health check."""
        result = {"status": "healthy", "details": {}}
        try:
            with self.get_connection() as conn:
                conn.execute("SELECT 1")
                result["details"]["connection"] = "ok"
                row = conn.execute("PRAGMA journal_mode").fetchone()
                result["details"]["journal_mode"] = row[0] if row else "unknown"
                db_path = self._config.db_path
                if os.path.exists(db_path):
                    result["details"]["db_size_mb"] = round(
                        os.path.getsize(db_path) / 1024**2, 2
                    )
                backups = self.query(
                    "SELECT COUNT(*) as cnt FROM backup_log WHERE status='success'"
                )
                result["details"]["total_backups"] = backups[0]["cnt"] if backups else 0
        except Exception as exc:
            result["status"] = "critical"
            result["details"]["error"] = str(exc)
            logger.error("Database health check failed: %s", exc)
        if self._pool:
            result["details"]["pool"] = self._pool.stats
        return result

    def close(self) -> None:
        if self._pool:
            self._pool.close_all()
            self._pool = None
        self._initialized = False
        logger.info("DatabaseManager closed")
