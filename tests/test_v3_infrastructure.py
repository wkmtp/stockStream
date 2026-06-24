"""V3.0 Infrastructure tests — 验证所有新增生产级模块。"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

# Ensure project root in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_stream_guard_import():
    """StreamGuard 可正常导入并实例化。"""
    from src.core.stream_guard import StreamGuard, StreamGuardConfig, StreamHealth
    cfg = StreamGuardConfig(check_interval=0.1, critical_threshold=2)
    guard = StreamGuard(config=cfg)
    assert guard.overall_health == StreamHealth.HEALTHY
    report = guard.get_health_report()
    assert "checks" in report
    assert len(report["checks"]) == 5


def test_stream_guard_heartbeat():
    """StreamGuard 心跳更新功能。"""
    from src.core.stream_guard import StreamGuard, StreamGuardConfig
    cfg = StreamGuardConfig(check_interval=0.1)
    guard = StreamGuard(config=cfg)
    guard.heartbeat_frame()
    guard.heartbeat_subtitle()
    guard.heartbeat_avatar()
    guard.heartbeat_tts()
    guard.set_ffmpeg_alive(True)
    report = guard.get_health_report()
    assert report["overall"] == "healthy"


def test_health_check_service_import():
    """HealthCheckService 可正常导入。"""
    from src.core.health_check import HealthCheckService, ModuleHealth, ModuleStatus
    hc = HealthCheckService()
    assert len(hc.MONITORED_MODULES) == 20
    hc.set_module_status("market_service", ModuleHealth.HEALTHY)
    # 异步方法需要事件循环


def test_cache_service_import():
    """CacheService 可正常导入并操作。"""
    from src.core.cache_service import CacheService, TTLCache, LRUCache

    # TTL cache
    ttl = TTLCache("test", default_ttl=60, maxsize=10)
    ttl.set("key1", {"price": 100})
    assert ttl.get("key1") == {"price": 100}
    assert ttl.get("missing") is None

    # LRU cache
    lru = LRUCache("test", maxsize=3)
    lru.set("a", 1)
    lru.set("b", 2)
    lru.set("c", 3)
    lru.set("d", 4)  # should evict 'a'
    assert lru.get("a") is None
    assert lru.get("b") == 2

    # Full service
    svc = CacheService(cache_root=tempfile.mkdtemp())
    svc.market.set("600519", {"price": 1850.0})
    assert svc.market.get("600519")["price"] == 1850.0
    stats = svc.get_all_stats()
    assert "ttl_caches" in stats
    assert "lru_caches" in stats


def test_resource_manager_import():
    """ResourceManager 可正常导入。"""
    from src.core.resource_manager import ResourceManager, ResourceConfig, ResourceLevel
    cfg = ResourceConfig(
        check_interval_sec=0.1,
        memory_warning_pct=70,
        memory_critical_pct=80,
    )
    mgr = ResourceManager(config=cfg, jetson_mode=False)
    snap = mgr.get_snapshot()
    assert snap is not None
    summary = mgr.get_summary()
    assert "cpu" in summary
    assert "memory" in summary


def test_db_manager_import():
    """DatabaseManager 可正常导入并使用 WAL 模式。"""
    from src.core.db_manager import DatabaseManager, DBConfig
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        cfg = DBConfig(db_path=db_path, wal_mode=True, pool_size=2)
        mgr = DatabaseManager(cfg)
        mgr.initialize()

        # Test execution
        mgr.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        mgr.execute("INSERT INTO test (name) VALUES (?)", ("hello",))
        rows = mgr.query("SELECT * FROM test")
        assert len(rows) == 1
        assert rows[0]["name"] == "hello"

        # Health check
        health = mgr.health_check()
        assert health["status"] == "healthy"
        assert health["details"]["journal_mode"] == "wal"

        mgr.close()


def test_backup_service_import():
    """BackupService 可正常导入。"""
    from src.core.backup_service import BackupService, BackupConfig
    cfg = BackupConfig(
        backup_dir=tempfile.mkdtemp(),
        retention_days=7,
        schedule_hour=3,
        compress=True,
    )
    svc = BackupService(cfg)
    records = svc.get_records()
    assert isinstance(records, list)


def test_update_manager_import():
    """UpdateManager 可正常导入并获取版本。"""
    from src.core.update_manager import UpdateManager, generate_version_file
    mgr = UpdateManager()
    ver = mgr.get_version()
    assert ver.version == "3.0.0"
    d = mgr.get_version_dict()
    assert d["version"] == "3.0.0"


def test_web_monitor_import():
    """WebMonitor router 可正常导入。"""
    from src.monitoring.web_monitor import router
    assert router is not None
    assert router.prefix == "/monitor"
    routes = [r.path for r in router.routes]
    assert "/stream" in routes or any("stream" in p for p in routes)


def test_v3_module_count_increases():
    """验证 V3.0 模块数量增加。"""
    # 验证关键模块文件存在
    v3_modules = [
        "src/core/stream_guard.py",
        "src/core/health_check.py",
        "src/core/cache_service.py",
        "src/core/resource_manager.py",
        "src/core/db_manager.py",
        "src/core/backup_service.py",
        "src/core/update_manager.py",
        "src/monitoring/web_monitor.py",
    ]
    for mod in v3_modules:
        assert Path(mod).exists(), f"Missing module: {mod}"

    # 验证文档存在
    docs = [
        "docs/DEPLOY.md",
        "docs/OPS.md",
        "docs/TROUBLESHOOTING.md",
        "docs/UPGRADE.md",
        "docs/BACKUP.md",
        "docs/production_audit.md",
        "docs/release_report.md",
    ]
    for doc in docs:
        assert Path(doc).exists(), f"Missing doc: {doc}"

    # 验证 systemd 服务
    assert Path("services/ai-live.service").exists()


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
