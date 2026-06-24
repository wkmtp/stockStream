"""Backup Service — 自动备份服务。

V3.0 Production: 每天备份数据库/配置/日志/交易记录。
  支持一键恢复，保留 30 天历史。
"""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import os
import shutil
import tarfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class BackupConfig:
    backup_dir: str = "backups"
    retention_days: int = 30
    schedule_hour: int = 3        # 凌晨 3 点
    compress: bool = True
    items: list[str] | None = None  # 要备份的目录/文件列表

    def __post_init__(self) -> None:
        if self.items is None:
            self.items = [
                "data/",           # 数据库
                "config/",         # 配置文件
                "logs/",           # 日志
                # "trading_records/" — 如需要可添加
            ]


@dataclass
class BackupRecord:
    name: str
    path: str
    size_bytes: int
    created_at: float
    items: list[str]
    compressed: bool


class BackupService:
    """自动备份服务。

    使用方式:
        backup = BackupService()
        await backup.start()
        # 或手动触发
        path = await backup.backup_now()
    """

    def __init__(self, config: BackupConfig | None = None) -> None:
        self._config = config or BackupConfig()
        self._running = False
        self._task: asyncio.Task | None = None
        self._records: list[BackupRecord] = []

        Path(self._config.backup_dir).mkdir(parents=True, exist_ok=True)

    # ── Lifecycle ──────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._schedule_loop())
        logger.info("BackupService started (dir=%s, daily@%02d:00)",
                    self._config.backup_dir, self._config.schedule_hour)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("BackupService stopped")

    async def _schedule_loop(self) -> None:
        """定时备份循环 — 每天 schedule_hour 执行。"""
        while self._running:
            try:
                now = datetime.now()
                target = now.replace(hour=self._config.schedule_hour, minute=0, second=0)
                if now >= target:
                    target = target.replace(day=target.day + 1)
                wait_seconds = (target - now).total_seconds()
                # 如果等待时间超过 25 小时，说明计算错误，使用 1 小时
                if wait_seconds > 90000 or wait_seconds <= 0:
                    wait_seconds = 3600
                logger.debug("Next backup in %.1f hours", wait_seconds / 3600)
                await asyncio.sleep(min(wait_seconds, 3600))  # 每 1h 检查一次

                now = datetime.now()
                if now.hour == self._config.schedule_hour and 0 <= now.minute < 5:
                    await self.backup_now()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("BackupService schedule error: %s", exc)
                await asyncio.sleep(60)

    # ── Backup ─────────────────────────────────────────────────────

    async def backup_now(self) -> str:
        """立即执行一次完整备份。"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"backup_{timestamp}"
        backup_dir = Path(self._config.backup_dir)

        if self._config.compress:
            path = await asyncio.to_thread(self._create_tar_backup, name, backup_dir)
        else:
            path = await asyncio.to_thread(self._create_dir_backup, name, backup_dir)

        size_bytes = os.path.getsize(path) if os.path.exists(path) else 0
        record = BackupRecord(
            name=name,
            path=str(path),
            size_bytes=size_bytes,
            created_at=time.time(),
            items=self._config.items or [],
            compressed=self._config.compress,
        )
        self._records.append(record)

        # 清理旧备份
        await self._cleanup()

        logger.info("Backup completed: %s (%.2f MB)", name, size_bytes / 1024**2)
        return str(path)

    def _create_tar_backup(self, name: str, backup_dir: Path) -> Path:
        """创建 .tar.gz 压缩备份。"""
        archive_path = backup_dir / f"{name}.tar.gz"
        with tarfile.open(archive_path, "w:gz") as tar:
            for item in self._config.items or []:
                item_path = Path(item)
                if item_path.exists():
                    tar.add(item_path, arcname=item_path.name)
        return archive_path

    def _create_dir_backup(self, name: str, backup_dir: Path) -> Path:
        """创建目录备份 (无压缩)。"""
        dest = backup_dir / name
        dest.mkdir(parents=True, exist_ok=True)
        for item in self._config.items or []:
            src = Path(item)
            if src.is_dir():
                shutil.copytree(src, dest / src.name, dirs_exist_ok=True)
            elif src.is_file():
                shutil.copy2(src, dest / src.name)
        return dest

    async def _cleanup(self) -> None:
        """清理超过 retention_days 的旧备份。"""
        retention_sec = self._config.retention_days * 86400
        now = time.time()
        backup_dir = Path(self._config.backup_dir)
        removed = 0
        for entry in backup_dir.iterdir():
            if entry.is_file() and (entry.suffix in (".tar.gz", ".gz")):
                if now - entry.stat().st_mtime > retention_sec:
                    try:
                        entry.unlink()
                        removed += 1
                    except OSError:
                        pass
            elif entry.is_dir() and entry.name.startswith("backup_"):
                if now - entry.stat().st_mtime > retention_sec:
                    try:
                        shutil.rmtree(entry)
                        removed += 1
                    except OSError:
                        pass
        if removed:
            logger.info("Cleaned up %d old backups", removed)

    # ── Restore ────────────────────────────────────────────────────

    async def restore(self, backup_path: str, target_dir: str = ".") -> bool:
        """从备份恢复。"""
        src = Path(backup_path)
        if not src.exists():
            logger.error("Backup file not found: %s", backup_path)
            return False

        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)

        try:
            if src.suffix == ".gz":
                # .tar.gz 恢复
                with tarfile.open(src, "r:gz") as tar:
                    tar.extractall(path=target)
            else:
                # 目录备份恢复
                for item in src.iterdir():
                    dest = target / item.name
                    if item.is_dir():
                        shutil.copytree(item, dest, dirs_exist_ok=True)
                    else:
                        shutil.copy2(item, dest)
            logger.info("Restore completed: %s → %s", backup_path, target_dir)
            return True
        except Exception as exc:
            logger.error("Restore failed: %s", exc)
            return False

    # ── Status ─────────────────────────────────────────────────────

    def get_records(self, limit: int = 30) -> list[dict]:
        """获取最近 N 条备份记录。"""
        records = self._records[-limit:]
        return [
            {
                "name": r.name,
                "path": r.path,
                "size_mb": round(r.size_bytes / 1024**2, 2),
                "created_at": datetime.fromtimestamp(r.created_at).isoformat(),
                "items": r.items,
                "compressed": r.compressed,
            }
            for r in records
        ]

    def get_latest(self) -> dict | None:
        records = self.get_records(limit=1)
        return records[0] if records else None


# ── 便捷函数 ────────────────────────────────────────────────────────


async def periodic_backup(backup_dir: str = "backups",
                          retention_days: int = 30,
                          schedule_hour: int = 3) -> BackupService:
    """创建并启动备份服务 (便捷函数)。"""
    config = BackupConfig(
        backup_dir=backup_dir,
        retention_days=retention_days,
        schedule_hour=schedule_hour,
    )
    service = BackupService(config)
    await service.start()
    return service
