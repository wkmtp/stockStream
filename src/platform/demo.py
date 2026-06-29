"""DemoAdapter — 客户演示 / 快速体验模式

目标: 零外部依赖演示
特性:
    - 模拟行情数据 (内置 K 线 / 分时)
    - 模拟弹幕互动
    - 模拟新闻播报
    - 模拟直播推流
    - 打开浏览器即可演示
    - 不需要东方财富 / 直播平台

Python 兼容: 3.8+
"""

from __future__ import annotations

import json
import os
import random
from pathlib import Path
from typing import Any

from src.platform.base import (
    GPUInfo,
    PlatformAdapter,
    PlatformInfo,
    PlatformType,
    ReleaseTarget,
    detect_platform,
)


class DemoAdapter(PlatformAdapter):
    """演示模式适配器 — 全模拟环境"""

    def __init__(self) -> None:
        self._info = detect_platform("desktop")  # 复用宿主机检测
        self._info.platform_type = PlatformType.DEMO
        self._info.release_target = ReleaseTarget.DEMO
        self._mock_port = int(os.environ.get("DEMO_PORT", "8080"))

    # ── Identity ─────────────────────────────────────────────────

    @property
    def platform_type(self) -> PlatformType:
        return PlatformType.DEMO

    @property
    def release_target(self) -> ReleaseTarget:
        return ReleaseTarget.DEMO

    def get_info(self) -> PlatformInfo:
        return self._info

    # ── Paths ────────────────────────────────────────────────────

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parent.parent.parent

    # ── GPU ───────────────────────────────────────────────────────

    @property
    def gpu_available(self) -> bool:
        # Demo 模式不强制使用 GPU
        if os.environ.get("DEMO_USE_GPU"):
            try:
                self._info = detect_platform("desktop")
                return self._info.gpu.available
            except Exception:
                pass
        return False

    def get_gpu_info(self) -> GPUInfo:
        return GPUInfo()  # 空 GPU

    def get_onnx_providers(self) -> list[str]:
        return ["CPUExecutionProvider"]

    def get_ort_session_options(self) -> dict[str, Any]:
        return {"providers": ["CPUExecutionProvider"]}

    # ── Resources ────────────────────────────────────────────────

    def get_memory_limit_mb(self) -> int:
        return 4096  # Demo 模式低内存

    def get_gpu_memory_limit_mb(self) -> int:
        return 0

    def get_cpu_threads(self) -> int:
        return 2

    def get_worker_count(self) -> int:
        return 1

    # ── TTS ──────────────────────────────────────────────────────

    def get_tts_engine(self) -> str:
        return "edge"  # 用 Edge TTS (免费，无需本地模型)

    def get_tts_model_path(self, voice: str) -> Path:
        return self.model_dir / f"{voice}.onnx"

    def supports_fp16_tts(self) -> bool:
        return False

    # ── Avatar ───────────────────────────────────────────────────

    def get_avatar_backend(self) -> str:
        return "mock"  # 静态图片 + 嘴型动画模拟

    def get_avatar_resolution(self) -> tuple[int, int]:
        return (854, 480)  # 低分辨率

    # ── Market ───────────────────────────────────────────────────

    def get_market_provider(self) -> str:
        return "mock"

    # ── Stream ───────────────────────────────────────────────────

    @property
    def stream_enabled(self) -> bool:
        return False  # Demo 不推流

    def get_stream_backend(self) -> str:
        return "mock"

    # ── Environment ──────────────────────────────────────────────

    def setup_environment(self) -> None:
        os.environ.setdefault("STOCKSTREAM_DEMO_MODE", "1")
        os.environ.setdefault("OMP_NUM_THREADS", "2")

    # ── Config ───────────────────────────────────────────────────

    def get_default_config_paths(self) -> list[str]:
        return [
            "configs/environment/base.yaml",
            "configs/environment/demo.yaml",
        ]

    # ── Safety ───────────────────────────────────────────────────

    def is_safe_to_use_gpu(self) -> bool:
        return False

    # ──────────────────────────────────────────────────────────────
    # Demo 专属: 模拟数据生成器
    # ──────────────────────────────────────────────────────────────

    def get_mock_market_data(self) -> dict[str, Any]:
        """生成模拟行情数据"""
        stocks = [
            {"code": "000001", "name": "平安银行", "price": 12.45},
            {"code": "000002", "name": "万科A", "price": 14.80},
            {"code": "600036", "name": "招商银行", "price": 35.20},
            {"code": "600519", "name": "贵州茅台", "price": 1680.00},
            {"code": "000858", "name": "五粮液", "price": 168.50},
        ]
        for s in stocks:
            s["change"] = round(random.uniform(-5, 5), 2)
            s["change_pct"] = round(s["change"] / s["price"] * 100, 2)
            s["volume"] = random.randint(10000, 1000000)
            s["high"] = round(s["price"] + random.uniform(0, 2), 2)
            s["low"] = round(s["price"] - random.uniform(0, 2), 2)
        return {"stocks": stocks, "timestamp": ""}

    def get_mock_news(self) -> list[dict[str, str]]:
        """生成模拟财经新闻"""
        templates = [
            {"title": "央行宣布降准0.5个百分点，释放长期资金约1万亿元", "source": "央行"},
            {"title": "A股三大指数集体收涨，北向资金净流入超百亿", "source": "证券时报"},
            {"title": "工信部：加快5G+工业互联网创新发展", "source": "新华社"},
            {"title": "新能源板块持续走强，光伏龙头创历史新高", "source": "财经网"},
            {"title": "国家统计局：上半年GDP同比增长5.5%", "source": "央视新闻"},
        ]
        return random.sample(templates, min(3, len(templates)))

    def get_mock_danmaku(self) -> list[dict[str, str]]:
        """生成模拟弹幕"""
        templates = [
            ("小明", "涨了涨了！"),
            ("股海老司机", "这波操作稳了"),
            ("投资达人", "什么时候回调啊"),
            ("韭菜一号", "求大佬带带"),
            ("财经观察", "强烈看好后市"),
            ("散户之光", "已上车，坐等起飞"),
            ("AI量化", "量化信号显示做多"),
            ("价值投资", "低估就是机会"),
        ]
        return [{"user": u, "text": t} for u, t in random.sample(
            templates, random.randint(2, 5)
        )]

    def get_demo_port(self) -> int:
        """演示 Web 端口"""
        return self._mock_port

    def get_demo_scenario(self) -> dict[str, Any]:
        """获取完整演示场景数据"""
        return {
            "market": self.get_mock_market_data(),
            "news": self.get_mock_news(),
            "danmaku": self.get_mock_danmaku(),
            "title": "AI数字人财经直播演示",
            "port": self._mock_port,
        }
