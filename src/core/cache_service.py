"""Cache Service — 统一缓存服务。

V3.0 Production: 缓存行情数据/图表/字幕/热点板块，自动过期。
  避免重复计算，支持 TTL + LRU + maxsize 三层淘汰策略。

架构：
  - TTL 缓存 (time-based): 行情快照、新闻、板块数据
  - LRU 缓存 (size-based): 图表 PNG、字幕 SRT、热力图
  - 文件缓存 (disk-based): 大尺寸二进制数据
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Generic, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class CacheEntry(Generic[T]):
    key: str
    value: T
    created_at: float = field(default_factory=time.monotonic)
    accessed_at: float = field(default_factory=time.monotonic)
    access_count: int = 0
    ttl_seconds: float | None = None     # None = 永不过期
    file_path: str | None = None          # 文件缓存路径

    @property
    def expired(self) -> bool:
        if self.ttl_seconds is None:
            return False
        return time.monotonic() - self.created_at > self.ttl_seconds

    def touch(self) -> None:
        self.accessed_at = time.monotonic()
        self.access_count += 1


class TTLCache(Generic[T]):
    """基于 TTL 的过期缓存 (适合行情/新闻等时效性数据)。"""

    def __init__(self, name: str, default_ttl: float = 5.0, maxsize: int = 10000) -> None:
        self.name = name
        self.default_ttl = default_ttl
        self.maxsize = maxsize
        self._data: dict[str, CacheEntry[T]] = {}
        self._lock = Lock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def get(self, key: str, default: T | None = None) -> T | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return default
            if entry.expired:
                del self._data[key]
                self._misses += 1
                self._evictions += 1
                return default
            entry.touch()
            self._hits += 1
            return entry.value

    def set(self, key: str, value: T, ttl: float | None = None) -> None:
        effective_ttl = ttl if ttl is not None else self.default_ttl
        with self._lock:
            # 驱逐过期项
            if len(self._data) >= self.maxsize:
                self._evict_expired()
            # 仍满则驱逐最旧项
            if len(self._data) >= self.maxsize:
                oldest = min(self._data.keys(), key=lambda k: self._data[k].created_at)
                del self._data[oldest]
                self._evictions += 1
            self._data[key] = CacheEntry(
                key=key, value=value, ttl_seconds=effective_ttl,
            )

    def delete(self, key: str) -> bool:
        with self._lock:
            return self._data.pop(key, None) is not None

    def clear(self) -> None:
        with self._lock:
            count = len(self._data)
            self._data.clear()
            logger.debug("TTLCache[%s]: cleared %d entries", self.name, count)

    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            return {
                "name": self.name,
                "size": len(self._data),
                "maxsize": self.maxsize,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": f"{self._hits / max(total, 1) * 100:.1f}%",
                "evictions": self._evictions,
            }

    def _evict_expired(self) -> int:
        expired = [k for k, e in self._data.items() if e.expired]
        for k in expired:
            del self._data[k]
        self._evictions += len(expired)
        return len(expired)


class LRUCache(Generic[T]):
    """基于 LRU 的大小限制缓存 (适合图表/字幕/热力图等)。"""

    def __init__(self, name: str, maxsize: int = 500) -> None:
        self.name = name
        self.maxsize = maxsize
        self._data: OrderedDict[str, CacheEntry[T]] = OrderedDict()
        self._lock = Lock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def get(self, key: str, default: T | None = None) -> T | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return default
            # Move to end (most recently used)
            self._data.move_to_end(key)
            entry.touch()
            self._hits += 1
            return entry.value

    def set(self, key: str, value: T) -> None:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self._data[key].value = value
                return
            if len(self._data) >= self.maxsize:
                # Evict least recently used (first item)
                evicted_key, _ = self._data.popitem(last=False)
                self._evictions += 1
                logger.debug("LRUCache[%s]: evicted %s", self.name, evicted_key)
            self._data[key] = CacheEntry(key=key, value=value)

    def delete(self, key: str) -> bool:
        with self._lock:
            return self._data.pop(key, None) is not None

    def clear(self) -> None:
        with self._lock:
            count = len(self._data)
            self._data.clear()
            logger.debug("LRUCache[%s]: cleared %d entries", self.name, count)

    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            return {
                "name": self.name,
                "size": len(self._data),
                "maxsize": self.maxsize,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": f"{self._hits / max(total, 1) * 100:.1f}%",
                "evictions": self._evictions,
            }


class CacheService:
    """统一缓存服务 — 管理多个 TTL/LRU/文件缓存实例。

    使用方式:
        cache = CacheService()
        cache.market.set("600519", {"price": 1850.00, "change": 2.3})
        price = cache.market.get("600519")

    缓存分区:
        market:      行情快照 (TTL 5s, max 50000)
        chart:       图表 PNG (LRU 500)
        subtitle:    字幕 SRT (LRU 200)
        heatmap:     热力图 (LRU 100)
        news:        新闻数据 (TTL 300s, max 1000)
        analysis:    分析结果 (TTL 60s, max 2000)
        sector:      板块数据 (TTL 10s, max 500)
    """

    def __init__(self, cache_root: str = "cache") -> None:
        self._cache_root = Path(cache_root)
        self._cache_root.mkdir(parents=True, exist_ok=True)

        # ── TTL 缓存 (时效性数据) ──
        self.market: TTLCache[dict] = TTLCache("market", default_ttl=5.0, maxsize=50000)
        self.news: TTLCache[dict] = TTLCache("news", default_ttl=300.0, maxsize=1000)
        self.analysis: TTLCache[dict] = TTLCache("analysis", default_ttl=60.0, maxsize=2000)
        self.sector: TTLCache[dict] = TTLCache("sector", default_ttl=10.0, maxsize=500)

        # ── LRU 缓存 (大小限制) ──
        self.chart: LRUCache[bytes] = LRUCache("chart", maxsize=500)
        self.subtitle: LRUCache[str] = LRUCache("subtitle", maxsize=200)
        self.heatmap: LRUCache[bytes] = LRUCache("heatmap", maxsize=100)
        self.dashboard: LRUCache[bytes] = LRUCache("dashboard", maxsize=100)

        # ── 文件缓存 ──
        self._file_registry: dict[str, CacheEntry] = {}

        self._cleanup_task: asyncio.Task | None = None
        self._running = False

        logger.info("CacheService initialized (root=%s)", self._cache_root)

    # ── File cache ─────────────────────────────────────────────────

    def get_file(self, key: str, default: str | None = None) -> str | None:
        entry = self._file_registry.get(key)
        if entry and entry.file_path and os.path.exists(entry.file_path):
            entry.touch()
            return entry.file_path
        return default

    def set_file(self, key: str, data: bytes, extension: str = ".png",
                 ttl: float | None = None) -> str:
        file_path = self._cache_root / f"{key}{extension}"
        file_path.write_bytes(data)
        self._file_registry[key] = CacheEntry(
            key=key, value=data, ttl_seconds=ttl,
            file_path=str(file_path),
        )
        return str(file_path)

    # ── Lifecycle ──────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("CacheService started")

    async def stop(self) -> None:
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
        logger.info("CacheService stopped")

    async def _cleanup_loop(self) -> None:
        """定期清理过期缓存 (60s 间隔)。"""
        while self._running:
            try:
                caches: list[TTLCache | LRUCache] = [
                    self.market, self.news, self.analysis, self.sector,
                    self.chart, self.subtitle, self.heatmap, self.dashboard,
                ]
                for cache in caches:
                    if hasattr(cache, '_evict_expired'):
                        evicted = cache._evict_expired()  # type: ignore[union-attr]
                        if evicted > 0:
                            logger.debug("%s: evicted %d expired entries", cache.name, evicted)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("CacheService cleanup error: %s", exc)
            await asyncio.sleep(60)

    # ── Stats ──────────────────────────────────────────────────────

    def get_all_stats(self) -> dict:
        return {
            "ttl_caches": {
                "market": self.market.stats(),
                "news": self.news.stats(),
                "analysis": self.analysis.stats(),
                "sector": self.sector.stats(),
            },
            "lru_caches": {
                "chart": self.chart.stats(),
                "subtitle": self.subtitle.stats(),
                "heatmap": self.heatmap.stats(),
                "dashboard": self.dashboard.stats(),
            },
            "file_cache": {
                "entries": len(self._file_registry),
                "disk_path": str(self._cache_root),
            },
        }

    def clear_all(self) -> None:
        """清空所有缓存 (内存压力时使用)。"""
        for cache in [self.market, self.news, self.analysis, self.sector]:
            cache.clear()
        for cache in [self.chart, self.subtitle, self.heatmap, self.dashboard]:
            cache.clear()
        self._file_registry.clear()
        logger.info("CacheService: all caches cleared")
