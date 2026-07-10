"""JetsonAdapter — ARM64 + JetPack 5.x + Python 3.8

目标: Jetson Xavier NX 8GB LTS Production Edition
JetPack: 5.x | CUDA: 11.4 | TensorRT: 8.x
Python: 3.8.10 (系统原生)

特性:
    - FP16 推理优先
    - TensorRT 加速
    - 内存 <6GB
    - GPU <80%
    - CPU <70%
    - 连续运行 30 天
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


class JetsonAdapter(PlatformAdapter):
    """Jetson Xavier NX 平台适配器 — Python 3.8 LTS"""

    def __init__(self) -> None:
        self._info = detect_platform("jetson")

    # ── Identity ─────────────────────────────────────────────────

    @property
    def platform_type(self) -> PlatformType:
        return PlatformType.JETSON

    @property
    def release_target(self) -> ReleaseTarget:
        return ReleaseTarget.PRODUCTION_JETSON

    def get_info(self) -> PlatformInfo:
        return self._info

    # ── Paths ────────────────────────────────────────────────────

    @property
    def project_root(self) -> Path:
        # Jetson 部署标准路径
        deployed = Path("/opt/stockstream")
        if deployed.exists():
            return deployed
        return Path(__file__).resolve().parent.parent.parent

    # ── GPU ───────────────────────────────────────────────────────

    @property
    def gpu_available(self) -> bool:
        return True  # Jetson 自带 GPU

    def get_gpu_info(self) -> GPUInfo:
        return self._info.gpu

    def get_onnx_providers(self) -> list[str]:
        """Jetson 优先 TensorRT → CUDA → CPU"""
        import onnxruntime as ort
        available = ort.get_available_providers()
        preferred = [
            "TensorrtExecutionProvider",
            "CUDAExecutionProvider",
            "CPUExecutionProvider",
        ]
        result = [p for p in preferred if p in available]
        return result if result else ["CPUExecutionProvider"]

    def get_ort_session_options(self) -> dict[str, Any]:
        """Jetson ONNX Runtime 优化选项 — FP16 优先, 显存受限"""
        opts: dict[str, Any] = {}
        providers = self.get_onnx_providers()
        opts["providers"] = providers

        provider_options: list[dict[str, Any]] = []
        for p in providers:
            if p == "TensorrtExecutionProvider":
                provider_options.append({
                    "device_id": 0,
                    "trt_fp16_enable": True,
                    "trt_int8_enable": False,  # 精度优先
                    "trt_engine_cache_enable": True,
                    "trt_engine_cache_path": str(self.cache_dir / "trt_engines"),
                    "trt_max_workspace_size": 1 * 1024 * 1024 * 1024,  # 1GB
                })
            elif p == "CUDAExecutionProvider":
                provider_options.append({
                    "device_id": 0,
                    "arena_extend_strategy": "kSameAsRequested",
                    "gpu_mem_limit": 3 * 1024 * 1024 * 1024,  # 3GB 上限
                    "cudnn_conv_algo_search": "HEURISTIC",
                    "do_copy_in_default_stream": True,
                })
            else:
                provider_options.append({})
        opts["provider_options"] = provider_options
        return opts

    # ── Resources ────────────────────────────────────────────────

    def get_memory_limit_mb(self) -> int:
        return 6144  # 6GB 总内存上限

    def get_gpu_memory_limit_mb(self) -> int:
        return 4096  # 4GB 显存上限 (8GB 共享内存中分配)

    def get_cpu_threads(self) -> int:
        return max(1, min(4, (os.cpu_count() or 6) - 2))

    def get_worker_count(self) -> int:
        return 1  # 单 worker, 节省内存

    # ── TTS ──────────────────────────────────────────────────────

    def get_tts_engine(self) -> str:
        return "piper"

    def get_tts_model_path(self, voice: str) -> Path:
        return self.model_dir / "piper" / f"{voice}.onnx"

    def supports_fp16_tts(self) -> bool:
        return True

    # ── Avatar ───────────────────────────────────────────────────

    def get_avatar_backend(self) -> str:
        return "wav2lip"

    def get_avatar_resolution(self) -> tuple[int, int]:
        return (512, 512)  # 低分辨率适配 Jetson 内存

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
        """Jetson 最优环境变量配置"""
        # CPU 亲和性
        os.environ.setdefault("OMP_NUM_THREADS", str(self.get_cpu_threads()))
        os.environ.setdefault("MKL_NUM_THREADS", "1")  # Jetson 无 MKL
        os.environ.setdefault("OPENBLAS_NUM_THREADS", str(self.get_cpu_threads()))
        os.environ.setdefault("NUMEXPR_NUM_THREADS", str(self.get_cpu_threads()))

        # GPU / TensorRT
        os.environ.setdefault("ORT_TENSORRT_FP16_ENABLE", "1")
        os.environ.setdefault("ORT_TENSORRT_ENGINE_CACHE_ENABLE", "1")
        os.environ.setdefault("ORT_TENSORRT_MAX_WORKSPACE_SIZE", "1073741824")  # 1GB

        # CUDA 限制
        os.environ.setdefault("CUDA_MODULE_LOADING", "LAZY")
        os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

        # Jetson 电源模式
        try:
            import subprocess
            subprocess.run(
                ["sudo", "nvpmodel", "-m", "2"],  # MODE_15W_6CORE
                capture_output=True, timeout=5,
            )
        except Exception:
            pass

    # ── Config ───────────────────────────────────────────────────

    def get_default_config_paths(self) -> list[str]:
        return [
            "configs/environment/base.yaml",
            "configs/environment/jetson.yaml",
            "configs/environment/production/jetson.yaml",
        ]

    # ── Safety ───────────────────────────────────────────────────

    def is_safe_to_use_gpu(self) -> bool:
        """检查 GPU 温度是否安全"""
        try:
            thermal_path = "/sys/devices/virtual/thermal/thermal_zone0/temp"
            if os.path.exists(thermal_path):
                with open(thermal_path, "r") as f:
                    temp = int(f.read().strip()) / 1000.0
                    if temp > 85.0:
                        return False  # 过热
        except Exception:
            pass

        # 检查内存
        try:
            import subprocess
            r = subprocess.run(
                ["free", "-m"], capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                for line in r.stdout.splitlines():
                    if "Mem:" in line:
                        parts = line.split()
                        if len(parts) >= 3:
                            available = int(parts[-1])
                            if available < 1024:  # <1GB 可用
                                return False
        except Exception:
            pass

        return True
