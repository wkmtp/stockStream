"""ServerAdapter — Linux Server CPU-only 推理

目标: 纯 CPU 部署 (云服务器 / 无 GPU)
Python: 3.8+
特性:
    - 纯 CPU 推理
    - 精简模型
    - 低内存占用
    - 适配云端部署
"""

from __future__ import annotations

import os
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


class ServerAdapter(PlatformAdapter):
    """Linux Server 适配器 — CPU-only"""

    def __init__(self) -> None:
        self._info = detect_platform("server")

    # ── Identity ─────────────────────────────────────────────────

    @property
    def platform_type(self) -> PlatformType:
        return PlatformType.SERVER

    @property
    def release_target(self) -> ReleaseTarget:
        return ReleaseTarget.PRODUCTION_DESKTOP  # 复用桌面生产配置

    def get_info(self) -> PlatformInfo:
        return self._info

    # ── Paths ────────────────────────────────────────────────────

    @property
    def project_root(self) -> Path:
        deployed = Path("/opt/stockstream")
        if deployed.exists():
            return deployed
        return Path(__file__).resolve().parent.parent.parent

    # ── GPU ───────────────────────────────────────────────────────

    @property
    def gpu_available(self) -> bool:
        return False

    def get_gpu_info(self) -> GPUInfo:
        return GPUInfo()

    def get_onnx_providers(self) -> list[str]:
        return ["CPUExecutionProvider"]

    def get_ort_session_options(self) -> dict[str, Any]:
        return {
            "providers": ["CPUExecutionProvider"],
            "provider_options": [{
                "arena_extend_strategy": "kNextPowerOfTwo",
            }],
            "intra_op_num_threads": self.get_cpu_threads(),
            "inter_op_num_threads": 2,
            "graph_optimization_level": 2,  # Extended
        }

    # ── Resources ────────────────────────────────────────────────

    def get_memory_limit_mb(self) -> int:
        return 8192  # 8GB

    def get_gpu_memory_limit_mb(self) -> int:
        return 0

    def get_cpu_threads(self) -> int:
        return max(1, (os.cpu_count() or 4))

    def get_worker_count(self) -> int:
        return max(1, (os.cpu_count() or 4) // 2)

    # ── TTS ──────────────────────────────────────────────────────

    def get_tts_engine(self) -> str:
        return "edge"  # Edge TTS 无需本地模型

    def get_tts_model_path(self, voice: str) -> Path:
        return self.model_dir / f"{voice}.onnx"

    def supports_fp16_tts(self) -> bool:
        return False

    # ── Avatar ───────────────────────────────────────────────────

    def get_avatar_backend(self) -> str:
        return "wav2lip"

    def get_avatar_resolution(self) -> tuple[int, int]:
        return (512, 512)  # CPU 低分辨率

    # ── Market ───────────────────────────────────────────────────

    def get_market_provider(self) -> str:
        return "akshare"

    # ── Stream ───────────────────────────────────────────────────

    @property
    def stream_enabled(self) -> bool:
        return True

    def get_stream_backend(self) -> str:
        return "ffmpeg_rtmp"

    # ── Environment ──────────────────────────────────────────────

    def setup_environment(self) -> None:
        threads = self.get_cpu_threads()
        os.environ.setdefault("OMP_NUM_THREADS", str(threads))
        os.environ.setdefault("MKL_NUM_THREADS", str(threads))
        os.environ.setdefault("OPENBLAS_NUM_THREADS", str(threads))
        os.environ.setdefault("NUMEXPR_NUM_THREADS", str(threads))

    # ── Config ───────────────────────────────────────────────────

    def get_default_config_paths(self) -> list[str]:
        return [
            "configs/environment/base.yaml",
            "configs/environment/server.yaml",
            "configs/environment/production/server.yaml",
        ]

    # ── Safety ───────────────────────────────────────────────────

    def is_safe_to_use_gpu(self) -> bool:
        return False
