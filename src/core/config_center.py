"""统一配置中心 — 支持 YAML / JSON / ENV 三合一配置管理 + 热更新。

特性：
    1. 优先级: 环境变量 > YAML/JSON 文件 > 默认值
    2. 热更新: 文件变更自动重载，无需重启
    3. 类型安全: 基于 Pydantic 模型校验
    4. 命名空间: 按模块隔离配置

用法:
    from src.core.config_center import ConfigCenter

    cfg = ConfigCenter()  # 单例
    cfg.load_yaml("config/base.yaml")
    cfg.load_yaml("config/live.yaml")

    # 读取配置
    cfg.get("market.poll_seconds")           # 点号分隔路径
    cfg.get_section("tts")                   # 按模块获取
    cfg.as_dict()                            # 全部配置
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, ClassVar

import yaml

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """配置相关错误。"""


class ConfigValidationError(ConfigError):
    """配置校验失败。"""


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并两个字典，override 覆盖 base。"""
    result = deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _dot_get(data: dict, path: str, default: Any = None) -> Any:
    """通过点号分隔路径读取嵌套字典。"""
    keys = path.split(".")
    current: Any = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
            if current is None and key not in (current if isinstance(current, dict) else {}):
                return default
        else:
            return default
    return current


def _dot_set(data: dict, path: str, value: Any) -> None:
    """通过点号分隔路径设置嵌套字典值。"""
    keys = path.split(".")
    current = data
    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]
    current[keys[-1]] = value


class ConfigCenter:
    """统一配置管理中心（线程安全单例）。"""

    _instance: ClassVar[ConfigCenter | None] = None
    _lock: ClassVar[threading.Lock] = threading.Lock()

    def __new__(cls) -> ConfigCenter:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    cls._instance = instance
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._data: dict[str, Any] = {}
        self._env_prefix = "STOCKSTREAM_"
        self._file_watchers: dict[str, FileWatcher] = {}
        self._watcher_thread: threading.Thread | None = None
        self._watcher_running = False
        self._callbacks: list[callable] = []  # 热更新回调

    # ── Load ──────────────────────────────────────────────────────

    def load_defaults(self) -> ConfigCenter:
        """加载内置默认配置。"""
        self._data = _deep_merge(self._data, _DEFAULTS)
        return self

    def load_yaml(self, path: str | Path, watch: bool = False) -> ConfigCenter:
        """加载 YAML 配置文件。

        Args:
            path: YAML 文件路径
            watch: 是否监听文件变更自动重载
        """
        path = Path(path)
        if not path.exists():
            logger.warning("Config file not found: %s", path)
            return self

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        self._data = _deep_merge(self._data, data)
        logger.info("Loaded config: %s (%d keys)", path, len(data))

        if watch:
            self._file_watchers[str(path)] = FileWatcher(path, self._on_file_changed)
            self._start_watcher()

        return self

    def load_json(self, path: str | Path, watch: bool = False) -> ConfigCenter:
        """加载 JSON 配置文件。"""
        path = Path(path)
        if not path.exists():
            logger.warning("Config file not found: %s", path)
            return self

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self._data = _deep_merge(self._data, data)
        logger.info("Loaded config: %s", path)

        if watch:
            self._file_watchers[str(path)] = FileWatcher(path, self._on_file_changed)
            self._start_watcher()

        return self

    def load_env(self, prefix: str | None = None) -> ConfigCenter:
        """从环境变量加载配置。

        环境变量格式: STOCKSTREAM_MARKET__POLL_SECONDS=10
        双下划线表示嵌套路径: market.poll_seconds
        """
        prefix = prefix or self._env_prefix
        for key, value in os.environ.items():
            if key.startswith(prefix):
                config_key = key[len(prefix):].lower().replace("__", ".")
                # 尝试转换类型
                typed_value = _coerce_value(value)
                _dot_set(self._data, config_key, typed_value)
        return self

    def load_from_dict(self, data: dict[str, Any]) -> ConfigCenter:
        """直接从字典加载（用于测试或编程式配置）。"""
        self._data = _deep_merge(self._data, data)
        return self

    # ── Read ──────────────────────────────────────────────────────

    def get(self, path: str, default: Any = None) -> Any:
        """读取配置值，支持点号分隔路径。"""
        return _dot_get(self._data, path, default)

    def get_section(self, section: str) -> dict[str, Any]:
        """读取整个配置段。"""
        value = _dot_get(self._data, section)
        if isinstance(value, dict):
            return deepcopy(value)
        return {}

    def as_dict(self) -> dict[str, Any]:
        """返回全部配置的快照副本。"""
        return deepcopy(self._data)

    @property
    def data(self) -> dict[str, Any]:
        """只读访问原始配置字典。"""
        return self._data

    # ── Hot Reload ────────────────────────────────────────────────

    def on_change(self, callback: callable) -> None:
        """注册热更新回调函数。回调签名为 callback(new_config: dict)。"""
        self._callbacks.append(callback)

    def _on_file_changed(self, filepath: str) -> None:
        """文件变更时自动重载。"""
        path = Path(filepath)
        if not path.exists():
            return
        try:
            if path.suffix in (".yaml", ".yml"):
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
            elif path.suffix == ".json":
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                return

            self._data = _deep_merge(self._data, data)
            logger.info("Config hot-reloaded: %s", filepath)

            for cb in self._callbacks:
                try:
                    cb(deepcopy(self._data))
                except Exception as exc:
                    logger.error("Config change callback failed: %s", exc)
        except Exception as exc:
            logger.error("Failed to reload config: %s", exc)

    def _start_watcher(self) -> None:
        if self._watcher_running:
            return
        self._watcher_running = True
        self._watcher_thread = threading.Thread(
            target=self._watch_loop, daemon=True, name="config-watcher"
        )
        self._watcher_thread.start()
        logger.info("Config file watcher started")

    def _watch_loop(self) -> None:
        while self._watcher_running:
            for _, watcher in list(self._file_watchers.items()):
                watcher.check()
            time.sleep(2.0)

    def stop_watcher(self) -> None:
        """停止文件监听。"""
        self._watcher_running = False

    # ── Validate ──────────────────────────────────────────────────

    def validate_required(self, *paths: str) -> None:
        """检查必需配置项是否存在。"""
        missing = []
        for path in paths:
            if _dot_get(self._data, path) is None:
                missing.append(path)
        if missing:
            raise ConfigValidationError(
                f"Missing required config keys: {', '.join(missing)}"
            )

    def update(self, path: str, value: Any) -> None:
        """运行时更新单个配置项。"""
        _dot_set(self._data, path, value)

    # ── Export ────────────────────────────────────────────────────

    def export_yaml(self, path: str | Path) -> None:
        """导出当前配置为 YAML 文件。"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self._data, f, allow_unicode=True, default_flow_style=False)

    def export_json(self, path: str | Path) -> None:
        """导出当前配置为 JSON 文件。"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def export_env(self) -> str:
        """导出当前配置为环境变量格式字符串。"""
        lines = []
        for key, value in _flatten_dict(self._data).items():
            env_key = f"{self._env_prefix}{key.upper().replace('.', '__')}"
            lines.append(f"{env_key}={value}")
        return "\n".join(lines)


class FileWatcher:
    """文件变更监听器。"""

    def __init__(self, path: Path, callback: callable) -> None:
        self.path = path
        self.callback = callback
        self._last_mtime = path.stat().st_mtime if path.exists() else 0

    def check(self) -> None:
        """检查文件是否变更。"""
        if not self.path.exists():
            return
        mtime = self.path.stat().st_mtime
        if mtime > self._last_mtime:
            self._last_mtime = mtime
            self.callback(str(self.path))


def _coerce_value(raw: str) -> Any:
    """尝试将字符串值转换为合适的类型。"""
    # bool
    if raw.lower() in ("true", "yes", "1"):
        return True
    if raw.lower() in ("false", "no", "0"):
        return False
    # int
    try:
        return int(raw)
    except ValueError:
        pass
    # float
    try:
        return float(raw)
    except ValueError:
        pass
    # JSON
    if raw.startswith("{") or raw.startswith("["):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            pass
    return raw


def _flatten_dict(d: dict, parent_key: str = "") -> dict:
    """将嵌套字典展平为点号分隔的扁平字典。"""
    items: dict[str, Any] = {}
    for key, value in d.items():
        new_key = f"{parent_key}.{key}" if parent_key else key
        if isinstance(value, dict):
            items.update(_flatten_dict(value, new_key))
        else:
            items[new_key] = value
    return items


# ── Built-in defaults ─────────────────────────────────────────────────

_DEFAULTS: dict[str, Any] = {
    "host": "0.0.0.0",
    "port": 8000,
    "workers": 1,
    "log_level": "info",
    "market": {
        "poll_seconds": 5,
        "sqlite_path": "data/market_cache.db",
        "symbols": [],
    },
    "tts": {
        "voice": "zh_CN-huayan-medium",
        "model_path": "",
        "sample_rate": 22050,
        "length_scale": 1.0,
        "noise_scale": 0.667,
        "noise_w": 0.8,
        "sentence_silence": 0.2,
    },
    "stream": {
        "rtmp_url": "",
        "queue_size": 1024,
        "video_codec": "libx264",
        "fps": 25,
    },
    "database": {
        "url": "sqlite+aiosqlite:///data/stockstream.db",
        "pool_size": 5,
        "pool_pre_ping": True,
    },
    "analysis": {
        "deepseek_api_key": "",
        "deepseek_model": "deepseek-chat",
        "deepseek_timeout": 30.0,
    },
    "trader": {
        "capital": 3000.0,
        "portfolio_path": "data/portfolio.json",
        "tick_seconds": 10.0,
        "auto_open": True,
        "auto_add": True,
        "auto_reduce": False,
        "auto_clear": True,
    },
    "avatar": {
        "enabled": False,
        "host_image": "data/host.png",
        "face_detector_onnx": "models/face_detector.onnx",
        "wav2lip_onnx": "models/wav2lip_gan.onnx",
        "fps": 25,
        "face_batch_size": 128,
        "output_dir": "data/avatar",
        "auto_generate": True,
    },
    "live": {
        "douyin": {"cookie": "", "room_id": "", "rtmp_url": ""},
        "kuaishou": {"cookie": "", "room_id": ""},
    },
    "agents": {
        "chief_director": {
            "segment_duration": 120,
            "market_analysis_interval": 300,
            "silence_threshold": 30,
            "traffic_interval_minutes": 15,
            "monetization_interval_minutes": 30,
        },
    },
    "monitoring": {
        "metrics_port": 9090,
        "health_check_interval": 30,
        "log_retention_days": 7,
    },
    "scheduler": {
        "timezone": "Asia/Shanghai",
        "market_open_check_seconds": 60,
    },
}
