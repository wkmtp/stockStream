"""日志中心 — 多级别、多输出、自动轮转。

特性:
    1. 六级日志: DEBUG / INFO / WARNING / ERROR / CRITICAL / TRACE
    2. 双输出: 文件 (轮转) + 控制台 (彩色)
    3. 日志轮转: 按时间 + 按大小
    4. 保留期: 默认 90 天
    5. 结构化日志: 支持 JSON 格式
    6. 模块隔离: 每个模块独立日志文件

用法:
    from src.core.log_center import LogCenter

    log = LogCenter()
    log.setup()
    logger = log.get_logger("market")
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar


@dataclass
class LogConfig:
    """日志配置。"""
    level: str = "INFO"
    log_dir: str = "logs"
    console: bool = True
    console_colored: bool = True
    file_enabled: bool = True
    file_per_module: bool = True
    json_format: bool = False
    max_bytes: int = 50 * 1024 * 1024  # 50MB per file
    backup_count: int = 30            # keep 30 files
    retention_days: int = 90          # keep 90 days
    rotation: str = "midnight"        # midnight / hourly / size
    format: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format: str = "%Y-%m-%d %H:%M:%S"
    modules_log_level: dict[str, str] = field(default_factory=dict)


# ANSI color codes
_COLORS = {
    "DEBUG": "\033[36m",     # cyan
    "INFO": "\033[32m",      # green
    "WARNING": "\033[33m",   # yellow
    "ERROR": "\033[31m",     # red
    "CRITICAL": "\033[35m",  # magenta
    "RESET": "\033[0m",
}

# 添加 TRACE 级别
_TRACE_LEVEL = 5
logging.addLevelName(_TRACE_LEVEL, "TRACE")


class _ColorFormatter(logging.Formatter):
    """彩色控制台格式化器。"""

    def format(self, record: logging.LogRecord) -> str:
        if record.levelname in _COLORS:
            record.levelname = f"{_COLORS[record.levelname]}{record.levelname}{_COLORS['RESET']}"
        return super().format(record)


class _JsonFormatter(logging.Formatter):
    """JSON 结构化格式化器。"""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info and record.exc_info[1]:
            entry["exception"] = str(record.exc_info[1])
        return json.dumps(entry, ensure_ascii=False)


class LogCenter:
    """日志管理中心 — 全局单例。"""

    _instance: ClassVar[LogCenter | None] = None
    _initialized: bool = False

    def __new__(cls) -> LogCenter:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self.config = LogConfig()
        self._handlers: dict[str, list[logging.Handler]] = {}
        self._setup_done = False

    def setup(self, config: LogConfig | None = None) -> LogCenter:
        """初始化日志系统。

        应用设置后可通过此方法重新配置。
        """
        if config:
            self.config = config

        # 确保日志目录存在
        log_dir = Path(self.config.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        # 根 logger
        root = logging.getLogger()
        root.setLevel(getattr(logging, self.config.level.upper(), logging.INFO))

        # 清除已有 handlers
        root.handlers.clear()

        # 控制台输出
        if self.config.console:
            console_handler = logging.StreamHandler(sys.stdout)
            if self.config.console_colored and sys.stdout.isatty():
                formatter = _ColorFormatter(self.config.format, self.config.date_format)
            else:
                formatter = logging.Formatter(self.config.format, self.config.date_format)
            console_handler.setFormatter(formatter)
            root.addHandler(console_handler)

        # 文件输出
        if self.config.file_enabled:
            # 主日志文件
            main_handler = self._create_rotating_handler(
                str(log_dir / "stockstream.log")
            )
            if self.config.json_format:
                main_handler.setFormatter(_JsonFormatter())
            else:
                main_handler.setFormatter(
                    logging.Formatter(self.config.format, self.config.date_format)
                )
            root.addHandler(main_handler)

            # 错误日志文件
            err_handler = self._create_rotating_handler(
                str(log_dir / "error.log")
            )
            err_handler.setLevel(logging.ERROR)
            err_handler.setFormatter(
                logging.Formatter(self.config.format, self.config.date_format)
            )
            root.addHandler(err_handler)

        # 模块日志级别
        for module_name, level in self.config.modules_log_level.items():
            logging.getLogger(module_name).setLevel(
                getattr(logging, level.upper(), logging.INFO)
            )

        self._setup_done = True
        logger = logging.getLogger(__name__)
        logger.info(
            "LogCenter initialized: level=%s dir=%s retention=%dd",
            self.config.level, self.config.log_dir, self.config.retention_days,
        )
        return self

    def get_logger(self, name: str) -> logging.Logger:
        """获取模块专用 logger。

        每个模块独立的文件 handler。
        """
        logger = logging.getLogger(name)

        if self.config.file_per_module and self.config.file_enabled:
            log_dir = Path(self.config.log_dir)
            log_dir.mkdir(parents=True, exist_ok=True)

            # 检查是否已添加
            handler_key = f"file_{name}"
            if handler_key not in self._handlers:
                module_handler = self._create_rotating_handler(
                    str(log_dir / f"{name}.log")
                )
                if self.config.json_format:
                    module_handler.setFormatter(_JsonFormatter())
                else:
                    module_handler.setFormatter(
                        logging.Formatter(self.config.format, self.config.date_format)
                    )
                logger.addHandler(module_handler)
                logger.propagate = False
                self._handlers[handler_key] = [module_handler]

        return logger

    def set_level(self, name: str, level: str) -> None:
        """运行时调整指定 logger 的日志级别。"""
        logging.getLogger(name).setLevel(
            getattr(logging, level.upper(), logging.INFO)
        )

    def trace(self, name: str, message: str, *args: Any, **kwargs: Any) -> None:
        """记录 TRACE 级别日志。"""
        logging.getLogger(name).log(_TRACE_LEVEL, message, *args, **kwargs)

    def rotate_now(self) -> None:
        """手动触发日志轮转。"""
        for name, handlers in self._handlers.items():
            for handler in handlers:
                if hasattr(handler, "doRollover"):
                    handler.doRollover()

    def clean_old_logs(self) -> int:
        """清理超过保留期的日志文件。"""
        log_dir = Path(self.config.log_dir)
        if not log_dir.exists():
            return 0

        cutoff = datetime.now().timestamp() - self.config.retention_days * 86400
        deleted = 0
        for f in log_dir.glob("*.log*"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    deleted += 1
            except OSError:
                pass
        return deleted

    def get_logs(self, module: str = "", lines: int = 100) -> list[str]:
        """获取最近的日志行（用于 Web 监控）。"""
        log_dir = Path(self.config.log_dir)
        pattern = f"{module}.log" if module else "stockstream.log"
        path = log_dir / pattern

        if not path.exists():
            return []

        try:
            with open(path, "r", encoding="utf-8") as f:
                # 读取最后 N 行
                all_lines = f.readlines()
                return [line.rstrip() for line in all_lines[-lines:]]
        except Exception:
            return []

    def _create_rotating_handler(self, filename: str) -> logging.Handler:
        """根据配置创建合适的轮转 handler。"""
        if self.config.rotation == "midnight":
            return logging.handlers.TimedRotatingFileHandler(
                filename,
                when="midnight",
                interval=1,
                backupCount=self.config.backup_count,
                encoding="utf-8",
            )
        elif self.config.rotation == "hourly":
            return logging.handlers.TimedRotatingFileHandler(
                filename,
                when="H",
                interval=1,
                backupCount=self.config.backup_count,
                encoding="utf-8",
            )
        else:  # size-based
            return logging.handlers.RotatingFileHandler(
                filename,
                maxBytes=self.config.max_bytes,
                backupCount=self.config.backup_count,
                encoding="utf-8",
            )


# 便捷获取 logger 的函数
def get_logger(name: str) -> logging.Logger:
    """获取模块 logger，自动注册文件输出。"""
    return LogCenter().get_logger(name)


# 便捷 trace
def trace(name: str, message: str, *args: Any, **kwargs: Any) -> None:
    LogCenter().trace(name, message, *args, **kwargs)
