"""DesktopAdapter — x86_64 + NVIDIA RTX GPU + Python 3.10+

用于: Windows / Ubuntu 开发机, RTX 系列显卡
发布目标: dev-desktop / production-desktop

特性:
    - CUDA 12.x 支持
    - FP16 + INT8 推理
    - 大模型尺寸
    - 多数字人
    - 高分辨率 (1920x1080)
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


class DesktopAdapter(PlatformAdapter):
    """x86_64 桌面平台适配器 (RTX GPU)。"""

    def __init__(self) -> None:
        self._info = detect_platform("desktop")

    # ── Identity ─────────────────────────────────────────────────

    @property
    def platform_type(self) -> PlatformType:
        return PlatformType.DESKTOP

    @property
    def release_target(self) -> ReleaseTarget:
        dev = os.environ.get("STOCKSTREAM_DEV_MODE")
        return ReleaseTarget.DEV_DESKTOP if dev else ReleaseTarget.PRODUCTION_DESKTOP

    def get_info(self) -> PlatformInfo:
        return self._info

    # ── Paths ────────────────────────────────────────────────────

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parent.parent.parent

    # ── GPU ───────────────────────────────────────────────────────

    @property
    def gpu_available(self) -> bool:
        return self._info.gpu.available

    def get_gpu_info(self) -> GPUInfo:
        return self._info.gpu

    def get_onnx_providers(self) -> list[str]:
        if self.gpu_available:
            return [
                "CUDAExecutionProvider",
                "CPUExecutionProvider",
            ]
        return ["CPUExecutionProvider"]

    def get_ort_session_options(self) -> dict[str, Any]:
        opts: dict[str, Any] = {}
        if self.gpu_available:
            opts.update({
                "providers": self.get_onnx_providers(),
                "provider_options": [{
                    "device_id": 0,
                    "arena_extend_strategy": "kNextPowerOfTwo",
                    "gpu_mem_limit": 4 * 1024 * 1024 * 1024,
                    "cudnn_conv_algo_search": "EXHAUSTIVE",
                    "do_copy_in_default_stream": True,
                }],
            })
        return opts

    # ── Resources ────────────────────────────────────────────────

    def get_memory_limit_mb(self) -> int:
        return 16384  # 16GB

    def get_gpu_memory_limit_mb(self) -> int:
        return 12288  # 12GB

    def get_cpu_threads(self) -> int:
        return max(1, (os.cpu_count() or 8) - 2)

    def get_worker_count(self) -> int:
        return 2

    # ── TTS ──────────────────────────────────────────────────────

    def get_tts_engine(self) -> str:
        return "piper"

    def get_tts_model_path(self, voice: str) -> Path:
        return self.model_dir / f"{voice}.onnx"

    def supports_fp16_tts(self) -> bool:
        return True

    # ── Avatar ───────────────────────────────────────────────────

    def get_avatar_backend(self) -> str:
        return "wav2lip"

    def get_avatar_resolution(self) -> tuple[int, int]:
        return (1920, 1080)

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
        os.environ.setdefault("OMP_NUM_THREADS", str(self.get_cpu_threads()))
        os.environ.setdefault("MKL_NUM_THREADS", str(self.get_cpu_threads()))
        os.environ.setdefault("OPENBLAS_NUM_THREADS", str(self.get_cpu_threads()))
        os.environ.setdefault("ORT_TENSORRT_FP16_ENABLE", "0")

    # ── Config ───────────────────────────────────────────────────

    def get_default_config_paths(self) -> list[str]:
        return [
            "configs/environment/base.yaml",
            "configs/environment/desktop.yaml",
            "configs/environment/production/desktop.yaml",
        ]

    # ── Safety ───────────────────────────────────────────────────

    def is_safe_to_use_gpu(self) -> bool:
        if not self.gpu_available:
            return False
        try:
            import cupy
            cupy.cuda.runtime.memGetInfo()
            return True
        except Exception:
            return False
