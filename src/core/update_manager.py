"""Update Manager — 版本更新管理器。

V3.0 Production: 版本检查、升级脚本生成、版本回滚。
  支持 Git tag 版本管理。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class VersionInfo:
    version: str = "3.0.0"
    build: str = ""
    git_commit: str = ""
    git_branch: str = ""
    build_date: str = ""
    dependencies: dict[str, str] = field(default_factory=dict)


@dataclass
class UpdateConfig:
    version_file: str = "VERSION"
    backup_dir: str = "backups/updates"
    pre_update_commands: list[str] = field(default_factory=list)
    post_update_commands: list[str] = field(default_factory=list)
    auto_check_interval_hours: int = 24


class UpdateManager:
    """版本更新管理器。

    使用方式:
        mgr = UpdateManager()
        info = mgr.get_version()
        available = mgr.check_for_updates()
        mgr.create_backup_before_update()
    """

    def __init__(self, config: UpdateConfig | None = None) -> None:
        self._config = config or UpdateConfig()
        self._history: list[dict] = []
        self._project_root = Path(os.getcwd())

        Path(self._config.backup_dir).mkdir(parents=True, exist_ok=True)

    # ── Version ────────────────────────────────────────────────────

    def get_version(self) -> VersionInfo:
        """获取当前版本信息。"""
        info = VersionInfo()

        # 从 VERSION 文件读取
        version_file = Path(self._config.version_file)
        if version_file.exists():
            lines = version_file.read_text().strip().split("\n")
            if lines:
                info.version = lines[0].strip()
                info.build = lines[1].strip() if len(lines) > 1 else ""
                info.build_date = lines[2].strip() if len(lines) > 2 else ""

        # 从 Git 获取
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=5,
                cwd=self._project_root,
            )
            if result.returncode == 0:
                info.git_commit = result.stdout.strip()
        except Exception:
            pass

        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, timeout=5,
                cwd=self._project_root,
            )
            if result.returncode == 0:
                info.git_branch = result.stdout.strip()
        except Exception:
            pass

        if not info.build_date:
            info.build_date = datetime.now().isoformat()

        return info

    def get_version_dict(self) -> dict:
        info = self.get_version()
        return {
            "version": info.version,
            "build": info.build,
            "git_commit": info.git_commit,
            "git_branch": info.git_branch,
            "build_date": info.build_date,
        }

    # ── Update check ───────────────────────────────────────────────

    def check_for_updates(self) -> dict:
        """检查是否有可用更新 (通过 Git fetch + tag 对比)。"""
        result: dict[str, Any] = {
            "current_version": self.get_version().version,
            "update_available": False,
            "latest_version": "",
            "changelog": "",
        }

        try:
            # Fetch tags
            subprocess.run(
                ["git", "fetch", "--tags"],
                capture_output=True, timeout=30,
                cwd=self._project_root,
            )

            # 获取最新 tag
            tag_result = subprocess.run(
                ["git", "describe", "--tags", "--abbrev=0"],
                capture_output=True, text=True, timeout=10,
                cwd=self._project_root,
            )
            if tag_result.returncode == 0:
                latest = tag_result.stdout.strip().lstrip("v")
                result["latest_version"] = latest
                result["update_available"] = latest != result["current_version"]
        except Exception as exc:
            result["error"] = str(exc)

        return result

    # ── Backup before update ───────────────────────────────────────

    def create_backup_before_update(self) -> str:
        """创建更新前备份。"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"pre_update_{timestamp}"
        backup_path = os.path.join(self._config.backup_dir, backup_name)
        os.makedirs(backup_path, exist_ok=True)

        # 备份当前版本信息
        version_file = os.path.join(backup_path, "version_backup.json")
        with open(version_file, "w") as f:
            json.dump(self.get_version_dict(), f, indent=2)

        # 备份关键配置
        for item in ["config/", "VERSION"]:
            src = Path(item)
            if src.exists():
                dest = Path(backup_path) / src.name
                if src.is_dir():
                    import shutil
                    shutil.copytree(src, dest, dirs_exist_ok=True)
                else:
                    import shutil
                    shutil.copy2(src, dest)

        # 记录到历史
        self._history.append({
            "action": "backup",
            "version": self.get_version().version,
            "path": backup_path,
            "timestamp": time.time(),
        })

        logger.info("Pre-update backup created: %s", backup_path)
        return backup_path

    # ── Rollback ───────────────────────────────────────────────────

    async def rollback(self, backup_path: str) -> bool:
        """回滚到指定备份。"""
        try:
            # 恢复版本文件
            version_file = os.path.join(backup_path, "version_backup.json")
            if os.path.exists(version_file):
                import shutil
                shutil.copy2(version_file, self._config.version_file)

            # 恢复配置
            config_backup = os.path.join(backup_path, "config")
            if os.path.exists(config_backup):
                import shutil
                shutil.copytree(config_backup, "config", dirs_exist_ok=True)

            self._history.append({
                "action": "rollback",
                "version": self.get_version().version,
                "path": backup_path,
                "timestamp": time.time(),
            })

            logger.info("Rollback completed: %s", backup_path)
            return True
        except Exception as exc:
            logger.error("Rollback failed: %s", exc)
            return False

    # ── History ────────────────────────────────────────────────────

    def get_update_history(self) -> list[dict]:
        return self._history[-50:]

    def record_update(self, from_version: str, to_version: str) -> None:
        self._history.append({
            "action": "update",
            "from": from_version,
            "to": to_version,
            "timestamp": time.time(),
        })
        logger.info("Update recorded: %s → %s", from_version, to_version)


# ── Generate VERSION file ──────────────────────────────────────────


def generate_version_file(version: str = "3.0.0", build: str = "") -> None:
    """生成 VERSION 文件。"""
    content = f"{version}\n{build}\n{datetime.now().isoformat()}\n"
    Path("VERSION").write_text(content)
    logger.info("VERSION file generated: %s", version)
