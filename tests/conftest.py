# ============================================================
# AI数字人财经直播平台 V4.0 — Pytest 全局配置
# ============================================================

from __future__ import annotations

import os
import sys
import pytest
from pathlib import Path

# ── 项目根路径 ──
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

# ── 测试环境变量 ──
os.environ.setdefault("STOCKSTREAM_ENV", "test")
os.environ.setdefault("STOCKSTREAM_LOG_LEVEL", "ERROR")


@pytest.fixture(scope="session")
def project_root() -> Path:
    """项目根目录"""
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def test_data_dir() -> Path:
    """测试数据目录"""
    d = PROJECT_ROOT / "tests" / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture(scope="session")
def platform_adapter():
    """获取当前平台适配器"""
    from src.platform import get_adapter
    return get_adapter()


@pytest.fixture
def mock_demo_mode(monkeypatch):
    """强制 Demo 模式"""
    monkeypatch.setenv("STOCKSTREAM_PLATFORM", "demo")
    from src.platform.base import reset_adapter
    reset_adapter()
    from src.platform import get_adapter
    return get_adapter()


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: 标记慢速测试")
    config.addinivalue_line("markers", "gpu: 需要 GPU")
    config.addinivalue_line("markers", "jetson: 仅 Jetson 平台")
    config.addinivalue_line("markers", "integration: 集成测试")
    config.addinivalue_line("markers", "stress: 压力测试")
