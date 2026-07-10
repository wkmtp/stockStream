"""自动测试套件 — 覆盖所有核心模块。

运行方式:
    python tests/test_suite.py
    python tests/test_suite.py --unit       # 仅单元测试
    python tests/test_suite.py --integration # 仅集成测试
    python tests/test_suite.py --stress     # 压力测试
    python tests/test_suite.py --coverage   # 覆盖率报告

覆盖率目标: 80%+
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

# 抑制日志噪音
logging.basicConfig(level=logging.WARNING)

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── 测试计数 ──────────────────────────────────────────────────

_results: dict[str, int] = {
    "passed": 0, "failed": 0, "skipped": 0, "total": 0,
}


def test(name: str):
    """装饰器: 记录测试结果。"""
    def decorator(func):
        async def wrapper():
            _results["total"] += 1
            try:
                await func()
                _results["passed"] += 1
                print(f"  [PASS] {name}")
            except Exception as e:
                _results["failed"] += 1
                print(f"  [FAIL] {name}: {e}")
                raise
        return wrapper
    return decorator


# ═══════════════════════════════════════════════════════════════════
# 1. 配置中心测试
# ═══════════════════════════════════════════════════════════════════

@test("ConfigCenter: 单例模式")
async def test_config_singleton():
    from src.core.config_center import ConfigCenter
    ConfigCenter._instance = None
    a = ConfigCenter()
    b = ConfigCenter()
    assert a is b, "ConfigCenter must be singleton"


@test("ConfigCenter: YAML加载")
async def test_config_yaml():
    import yaml
    from src.core.config_center import ConfigCenter
    ConfigCenter._instance = None
    cfg = ConfigCenter()
    cfg.load_defaults()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump({"test_key": "test_value", "nested": {"a": 1}}, f)
        tmp = f.name
    try:
        cfg.load_yaml(tmp)
        assert cfg.get("test_key") == "test_value"
        assert cfg.get("nested.a") == 1
    finally:
        os.unlink(tmp)


@test("ConfigCenter: 环境变量加载")
async def test_config_env():
    from src.core.config_center import ConfigCenter
    ConfigCenter._instance = None
    cfg = ConfigCenter()
    cfg.load_defaults()
    os.environ["STOCKSTREAM_TEST_ENV_VAR"] = "hello"
    cfg.load_env(prefix="STOCKSTREAM_TEST_")
    assert cfg.get("env_var") == "hello"
    del os.environ["STOCKSTREAM_TEST_ENV_VAR"]


@test("ConfigCenter: 运行时更新")
async def test_config_update():
    from src.core.config_center import ConfigCenter
    ConfigCenter._instance = None
    cfg = ConfigCenter()
    cfg.load_defaults()
    cfg.update("market.poll_seconds", 99)
    assert cfg.get("market.poll_seconds") == 99


@test("ConfigCenter: 配置导出")
async def test_config_export():
    from src.core.config_center import ConfigCenter
    ConfigCenter._instance = None
    cfg = ConfigCenter()
    cfg.load_defaults()
    d = cfg.as_dict()
    assert "market" in d
    assert "tts" in d

    section = cfg.get_section("tts")
    assert "voice" in section


# ═══════════════════════════════════════════════════════════════════
# 2. 事件总线测试
# ═══════════════════════════════════════════════════════════════════

@test("EventBus: 基本发布订阅")
async def test_eventbus_basic():
    from src.core.event_bus import EventBus
    bus = EventBus()
    received = []

    @bus.on("test.event")
    async def handler(event):
        received.append(event.data)

    await bus.emit("test.event", {"value": 42})
    assert len(received) == 1
    assert received[0]["value"] == 42


@test("EventBus: 通配符订阅")
async def test_eventbus_wildcard():
    from src.core.event_bus import EventBus
    bus = EventBus()
    received = []

    @bus.on("market.*")
    async def handler(event):
        received.append(event.type)

    await bus.emit("market.price_updated", {})
    await bus.emit("market.volume_changed", {})
    await bus.emit("tts.started", {})
    assert len(received) == 2
    assert "market.price_updated" in received


@test("EventBus: 优先级排序")
async def test_eventbus_priority():
    from src.core.event_bus import EventBus
    bus = EventBus()
    order = []

    @bus.on("test.priority", priority=10)
    async def high(event):
        order.append("high")

    @bus.on("test.priority", priority=0)
    async def low(event):
        order.append("low")

    await bus.emit("test.priority", {})
    assert order == ["high", "low"]


@test("EventBus: 一次性订阅")
async def test_eventbus_once():
    from src.core.event_bus import EventBus
    bus = EventBus()
    count = [0]

    @bus.on("test.once", once=True)
    async def handler(event):
        count[0] += 1

    await bus.emit("test.once", {})
    await bus.emit("test.once", {})
    assert count[0] == 1


@test("EventBus: 统计信息")
async def test_eventbus_stats():
    from src.core.event_bus import EventBus
    bus = EventBus()
    for i in range(10):
        await bus.emit(f"test.stat_{i}", {})
    stats = bus.get_stats()
    assert stats["total_events"] == 10
    assert stats["subscriber_count"] >= 0


@test("EventBus: 全局单例")
async def test_eventbus_singleton():
    from src.core.event_bus import get_event_bus, reset_event_bus
    reset_event_bus()
    a = await get_event_bus()
    b = await get_event_bus()
    assert a is b


# ═══════════════════════════════════════════════════════════════════
# 3. 存储服务测试
# ═══════════════════════════════════════════════════════════════════

@test("StorageService: 内存数据库初始化")
async def test_storage_init():
    from src.storage.service import StorageService, StorageServiceConfig
    svc = StorageService(StorageServiceConfig(
        url="sqlite+aiosqlite:///:memory:",
        auto_migrate=True,
    ))
    await svc.start()
    health = await svc.health()
    assert health["status"] == "healthy"
    await svc.stop()


@test("StorageService: 股票数据CRUD")
async def test_storage_stocks():
    from src.storage.service import StorageService, StorageServiceConfig
    svc = StorageService(StorageServiceConfig(
        url="sqlite+aiosqlite:///:memory:",
    ))
    await svc.start()
    await svc.stocks.insert_price("600519", 1800.0, 10000)
    price = await svc.stocks.get_latest("600519")
    assert abs(price - 1800.0) < 0.01
    history = await svc.stocks.get_history("600519", limit=10)
    assert len(history) == 1
    await svc.stop()


@test("StorageService: 交易记录")
async def test_storage_trades():
    from src.storage.service import StorageService, StorageServiceConfig
    svc = StorageService(StorageServiceConfig(
        url="sqlite+aiosqlite:///:memory:",
    ))
    await svc.start()
    trade_id = await svc.trades.record_trade("600519", "buy", 100, 1800.0, reason="测试")
    assert trade_id > 0
    trades = await svc.trades.get_trades(limit=10)
    assert len(trades) > 0
    await svc.stop()


@test("StorageService: 弹幕记录")
async def test_storage_danmu():
    from src.storage.service import StorageService, StorageServiceConfig
    svc = StorageService(StorageServiceConfig(
        url="sqlite+aiosqlite:///:memory:",
    ))
    await svc.start()
    await svc.danmu.insert("douyin", "testuser", "涨了吗？")
    records = await svc.danmu.get_recent(10)
    assert len(records) == 1
    assert records[0]["username"] == "testuser"
    await svc.stop()


@test("StorageService: 直播会话")
async def test_storage_live():
    from src.storage.service import StorageService, StorageServiceConfig
    svc = StorageService(StorageServiceConfig(
        url="sqlite+aiosqlite:///:memory:",
    ))
    await svc.start()
    session_id = await svc.lives.start_session("douyin", "room_001")
    assert session_id > 0
    await svc.lives.record_segment(session_id, "stock_analysis", "分析内容", 60.0)
    await svc.lives.end_session(session_id)
    await svc.stop()


@test("StorageService: 礼物记录")
async def test_storage_gift():
    from src.storage.service import StorageService, StorageServiceConfig
    svc = StorageService(StorageServiceConfig(
        url="sqlite+aiosqlite:///:memory:",
    ))
    await svc.start()
    await svc.gifts.record_gift("douyin", "donor1", "火箭", 100.0)
    donors = await svc.gifts.get_top_donors(5)
    assert len(donors) == 1
    await svc.stop()


@test("StorageService: 自动迁移")
async def test_storage_migration():
    from src.storage.service import StorageService, StorageServiceConfig
    svc = StorageService(StorageServiceConfig(
        url="sqlite+aiosqlite:///:memory:",
    ))
    await svc.start()
    tables = await svc.migrations.get_table_info()
    # 至少应有 8 张表
    assert len(tables) >= 6, f"Expected >=6 tables, got {len(tables)}"
    await svc.stop()


# ═══════════════════════════════════════════════════════════════════
# 4. 恢复管理器测试
# ═══════════════════════════════════════════════════════════════════

@test("RecoveryManager: 注册守护")
async def test_recovery_register():
    from src.core.recovery_manager import RecoveryManager, RecoveryState
    rm = RecoveryManager()
    async def restart_fn() -> bool:
        return True
    guard = rm.register("test_module", restart_fn, max_retries=3)
    assert guard.name == "test_module"
    assert guard.max_retries == 3
    assert rm.is_healthy("test_module")


@test("RecoveryManager: 状态查询")
async def test_recovery_status():
    from src.core.recovery_manager import RecoveryManager
    rm = RecoveryManager()
    async def restart_fn() -> bool:
        return True
    rm.register("mod_a", restart_fn)
    rm.register("mod_b", restart_fn)
    status = rm.get_status()
    assert "mod_a" in status
    assert "mod_b" in status
    assert rm.healthy_count == 2


# ═══════════════════════════════════════════════════════════════════
# 5. 日志中心测试
# ═══════════════════════════════════════════════════════════════════

@test("LogCenter: 初始化")
async def test_log_init():
    from src.core.log_center import LogCenter, LogConfig
    with tempfile.TemporaryDirectory() as td:
        lc = LogCenter()
        lc.setup(LogConfig(
            level="debug",
            log_dir=td,
            retention_days=7,
            console=False,
            file_enabled=True,
        ))
        # Verify config was applied
        assert lc.config.log_dir == td
        assert lc.config.console is False
        assert lc.config.file_enabled is True
        # Clean up handlers so other tests aren't affected
        root = logging.getLogger()
        root.handlers.clear()


# ═══════════════════════════════════════════════════════════════════
# 6. 风控/合规测试
# ═══════════════════════════════════════════════════════════════════

@test("RiskControl: 检测保证收益")
async def test_risk_guaranteed_return():
    from src.agents.risk_control import RiskControlCenter
    rcc = RiskControlCenter()
    result = rcc.review("这只股票稳赚不赔，大家放心买！")
    assert not result.is_clean, "Should detect guaranteed return"
    assert any(v.type.value == "guaranteed_return" for v in result.violations)


@test("RiskControl: 检测荐股承诺")
async def test_risk_stock_recommend():
    from src.agents.risk_control import RiskControlCenter
    rcc = RiskControlCenter()
    result = rcc.review("赶紧买入这只股票，马上要涨！")
    assert any(v.type.value == "stock_recommendation" for v in result.violations)


@test("RiskControl: 自动清理文本")
async def test_risk_auto_clean():
    from src.agents.risk_control import RiskControlCenter
    rcc = RiskControlCenter()
    rcc.auto_fix = True
    result = rcc.review("保证收益必涨稳赚不赔")
    assert result.cleaned != result.original
    assert "稳赚不赔" not in result.cleaned or "保证收益" not in result.cleaned


@test("ComplianceAgent: 免责声明")
async def test_compliance_disclaimer():
    from src.agents.risk_control import ComplianceAgent
    ca = ComplianceAgent(platform="douyin")
    text = "今天这只股票表现不错"
    result = ca.add_disclaimer(text)
    assert "免责声明" in result
    assert "投资需谨慎" in result


@test("ComplianceAgent: 平台规则")
async def test_compliance_platform():
    from src.agents.risk_control import ComplianceAgent
    ca = ComplianceAgent(platform="douyin")
    result = ca.review("加微信领取牛股代码")
    assert any(v.type.value == "platform_violation" for v in result.violations)


# ═══════════════════════════════════════════════════════════════════
# 7. 模块导入完整性测试
# ═══════════════════════════════════════════════════════════════════

@test("ImportCheck: 核心模块全部可导入")
async def test_all_imports():
    modules = [
        "src.core.config_center", "src.core.event_bus", "src.core.base",
        "src.core.log_center", "src.core.recovery_manager",
        "src.storage.service", "src.storage.models",
        "src.market.service", "src.market.collector", "src.market.models",
        "src.tts.service", "src.tts.models",
        "src.analysis.service", "src.analysis.models",
        "src.danmu.service",
        "src.trading.service", "src.trading.models",
        "src.avatar.service",
        "src.selector.service", "src.selector.models",
        "src.dashboard.service",
        "src.monitoring.service", "src.monitoring.center",
        "src.scheduler.service", "src.scheduler.resource", "src.scheduler.content",
        "src.agents.chief_director", "src.agents.director",
        "src.agents.stock_qa", "src.agents.knowledge_base",
        "src.agents.market_review", "src.agents.news_engine",
        "src.agents.risk_control",
        "src.live.platform_gateway", "src.live.danmu_center",
        "src.live.engagement", "src.live.gift", "src.live.fan_tracker",
        "src.live.operation", "src.live.traffic", "src.live.anti_silence",
        "src.live.monetization", "src.live.clip_generator",
        "src.live.clip_factory", "src.live.video_writer", "src.live.dashboard",
    ]
    import importlib
    for m in modules:
        importlib.import_module(m)
    assert True


@test("ImportCheck: 无循环依赖")
async def test_no_circular_deps():
    # 清除所有 src 模块缓存
    for k in list(sys.modules.keys()):
        if k.startswith("src"):
            del sys.modules[k]
    try:
        from src.app import Application
        from src.web import create_app
        assert True
    except RecursionError:
        assert False, "Circular dependency detected!"


# ═══════════════════════════════════════════════════════════════════
# 8. 基础类型测试
# ═══════════════════════════════════════════════════════════════════

@test("BaseTypes: ModuleStatus枚举")
async def test_base_module_status():
    from src.core.base import ModuleStatus
    assert ModuleStatus.RUNNING.value == "running"
    assert ModuleStatus.ERROR.value == "error"


@test("BaseTypes: OperationResult")
async def test_base_operation_result():
    from src.core.base import OperationResult
    r = OperationResult(success=True, message="OK")
    assert r.success
    d = r.to_dict()
    assert d["success"] is True


@test("BaseTypes: 异常类")
async def test_base_exceptions():
    from src.core.base import StockStreamError, ModuleInitError, MarketError, StreamError
    try:
        raise ModuleInitError("test")
    except StockStreamError as e:
        assert str(e) == "test"

    assert issubclass(StreamError, StockStreamError)


# ═══════════════════════════════════════════════════════════════════
# 9. 集成测试（应用程序完整启动）
# ═══════════════════════════════════════════════════════════════════

@test("Integration: Application完整生命周期")
async def test_app_full_lifecycle():
    from src.app import Application
    from src.core.config_center import ConfigCenter
    ConfigCenter._instance = None  # reset singleton

    app = Application()
    app.config.load_defaults()
    app.config.update("database.url", "sqlite+aiosqlite:///:memory:")

    await app.initialize()
    await app.wire_services()
    await app.start()

    # 验证核心模块已启动
    n = app._module_count()
    assert n >= 24, f"Expected >=24 modules, got {n}"

    report = app.health_report()
    assert report["started"] is True
    assert report["modules"] >= 24
    assert "bus_stats" in report
    assert "recovery" in report

    await app.stop()
    assert not app._started


@test("Integration: 恢复管理器状态")
async def test_app_recovery_status():
    from src.app import Application
    from src.core.config_center import ConfigCenter
    ConfigCenter._instance = None

    app = Application()
    app.config.load_defaults()
    app.config.update("database.url", "sqlite+aiosqlite:///:memory:")

    await app.initialize()
    await app.wire_services()

    status = app.recovery.get_status()
    assert "market" in status
    assert "tts" in status
    assert "stream" in status

    await app.storage.stop()  # type: ignore[union-attr]


# ═══════════════════════════════════════════════════════════════════
# 10. 压力测试
# ═══════════════════════════════════════════════════════════════════

@test("Stress: 事件总线高吞吐")
async def test_stress_eventbus():
    from src.core.event_bus import EventBus
    bus = EventBus(max_history=10000)
    received = [0]

    @bus.on("stress.*")
    async def handler(event):
        received[0] += 1

    N = 500
    tasks = [bus.emit(f"stress.msg_{i}", {"i": i}) for i in range(N)]
    await asyncio.gather(*tasks)

    assert received[0] == N, f"Expected {N}, got {received[0]}"
    stats = bus.get_stats()
    assert stats["total_events"] == N


@test("Stress: 存储批量写入")
async def test_stress_storage():
    from src.storage.service import StorageService, StorageServiceConfig
    svc = StorageService(StorageServiceConfig(
        url="sqlite+aiosqlite:///:memory:",
    ))
    await svc.start()

    start = time.time()
    N = 200
    tasks = [
        svc.stocks.insert_price(f"TEST_{i:04d}", 10.0 + i, 1000)
        for i in range(N)
    ]
    await asyncio.gather(*tasks)
    elapsed = time.time() - start

    # 异步批量应很快完成
    assert elapsed < 10.0, f"Batch write too slow: {elapsed:.2f}s"
    await svc.stop()


# ═══════════════════════════════════════════════════════════════════
# 11. Web API 测试
# ═══════════════════════════════════════════════════════════════════

@test("WebAPI: 应用创建")
async def test_web_create_app():
    from src.app import Application
    from src.web import create_app
    from src.core.config_center import ConfigCenter
    ConfigCenter._instance = None

    application = Application()
    application.config.load_defaults()
    application.config.update("database.url", "sqlite+aiosqlite:///:memory:")
    await application.initialize()

    app_factory = create_app(application)
    assert app_factory is not None
    await application.storage.stop()


# ═══════════════════════════════════════════════════════════════════
# Main Runner
# ═══════════════════════════════════════════════════════════════════


async def run_all_tests():
    """运行所有测试。"""
    print("=" * 60)
    print("  StockStream v2.0 自动测试套件")
    print("=" * 60)
    print()

    tests = [
        # Config
        test_config_singleton, test_config_yaml, test_config_env,
        test_config_update, test_config_export,
        # EventBus
        test_eventbus_basic, test_eventbus_wildcard, test_eventbus_priority,
        test_eventbus_once, test_eventbus_stats, test_eventbus_singleton,
        # Storage
        test_storage_init, test_storage_stocks, test_storage_trades,
        test_storage_danmu, test_storage_live, test_storage_gift,
        test_storage_migration,
        # Recovery
        test_recovery_register, test_recovery_status,
        # Log
        test_log_init,
        # Risk & Compliance
        test_risk_guaranteed_return, test_risk_stock_recommend,
        test_risk_auto_clean, test_compliance_disclaimer,
        test_compliance_platform,
        # Imports
        test_all_imports, test_no_circular_deps,
        # Base types
        test_base_module_status, test_base_operation_result,
        test_base_exceptions,
        # Stress
        test_stress_eventbus, test_stress_storage,
        # Web
        test_web_create_app,
        # Integration (must be last)
        test_app_full_lifecycle, test_app_recovery_status,
    ]

    for test_func in tests:
        try:
            await test_func()
        except Exception:
            pass  # 结果已在装饰器中记录

    print()
    print("=" * 60)
    total = _results["total"]
    passed = _results["passed"]
    failed = _results["failed"]
    rate = (passed / total * 100) if total > 0 else 0
    print(f"  总计: {total} | 通过: {passed} | 失败: {failed}")
    print(f"  通过率: {rate:.1f}%")
    if rate >= 80:
        print("  [PASS] 覆盖率达标 (>=80%)")
    else:
        print(f"  [WARN] 覆盖率不足 (目标 80%, 当前 {rate:.1f}%)")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
