"""平台适配器基类 — V4.0 Enterprise Edition

定义所有平台适配器的统一抽象接口。
所有业务代码通过此接口访问平台能力，实现零平台耦合。

Design Pattern: Adapter Pattern + Strategy Pattern
Python 兼容: 3.8+ (Jetson Xavier NX LTS)
"""

from __future__ import annotations

import abc
import enum
import logging
import os
import platform as _platform
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# Platform Types
# ══════════════════════════════════════════════════════════════════════

class PlatformType(str, enum.Enum):
    """目标平台枚举。"""
    DESKTOP = "desktop"       # x86_64, RTX GPU, Python 3.10+
    JETSON = "jetson"         # ARM64, JetPack 5.x, Python 3.8
    DEMO = "demo"             # 任意平台, 模拟模式
    SERVER = "server"         # Linux Server, CPU-only


class ReleaseTarget(str, enum.Enum):
    """发布目标枚举（与 PlatformType 一一对应）。"""
    DEV_DESKTOP = "dev-desktop"
    DEMO = "demo"
    PRODUCTION_DESKTOP = "production-desktop"
    PRODUCTION_JETSON = "production-jetson"


# ══════════════════════════════════════════════════════════════════════
# Platform Info
# ══════════════════════════════════════════════════════════════════════

@dataclass
class GPUInfo:
    """GPU 能力描述。"""
    available: bool = False
    name: str = ""
    memory_mb: int = 0
    cuda_version: str = ""
    cuda_compute_capability: str = ""
    tensorrt_version: str = ""
    fp16_support: bool = False
    int8_support: bool = False


@dataclass
class PlatformInfo:
    """完整平台信息。"""
    platform_type: PlatformType = PlatformType.DESKTOP
    release_target: ReleaseTarget = ReleaseTarget.PRODUCTION_DESKTOP
    os_name: str = ""
    os_version: str = ""
    python_version: str = ""
    arch: str = ""
    cpu_count: int = 1
    total_ram_mb: int = 0
    gpu: GPUInfo = field(default_factory=GPUInfo)
    is_jetson: bool = False
    is_windows: bool = False
    is_linux: bool = False

    def summary(self) -> str:
        return (
            f"Platform={self.platform_type.value} | "
            f"OS={self.os_name} {self.arch} | "
            f"Python={self.python_version} | "
            f"GPU={'YES' if self.gpu.available else 'NO'} "
            f"({'CUDA ' + self.gpu.cuda_version if self.gpu.cuda_version else 'N/A'})"
        )


# ══════════════════════════════════════════════════════════════════════
# Abstract Platform Adapter
# ══════════════════════════════════════════════════════════════════════

class PlatformAdapter(abc.ABC):
    """平台适配器抽象基类。

    所有平台特定行为通过此接口暴露。
    子类必须实现所有 abstractmethod。
    """

    # ────────────────────────────────────────────────────────────────
    # Identity
    # ────────────────────────────────────────────────────────────────

    @property
    @abc.abstractmethod
    def platform_type(self) -> PlatformType:
        """平台类型。"""
        ...

    @property
    @abc.abstractmethod
    def release_target(self) -> ReleaseTarget:
        """发布目标。"""
        ...

    @abc.abstractmethod
    def get_info(self) -> PlatformInfo:
        """返回完整平台信息。"""
        ...

    # ────────────────────────────────────────────────────────────────
    # Paths
    # ────────────────────────────────────────────────────────────────

    @property
    @abc.abstractmethod
    def project_root(self) -> Path:
        """项目根目录 (统一 Linux 风格)。"""
        ...

    @property
    def config_dir(self) -> Path:
        return self.project_root / "configs"

    @property
    def data_dir(self) -> Path:
        return self.project_root / "data"

    @property
    def cache_dir(self) -> Path:
        return self.project_root / "cache"

    @property
    def log_dir(self) -> Path:
        return self.project_root / "logs"

    @property
    def model_dir(self) -> Path:
        return self.project_root / "models"

    # ────────────────────────────────────────────────────────────────
    # GPU / Inference
    # ────────────────────────────────────────────────────────────────

    @property
    @abc.abstractmethod
    def gpu_available(self) -> bool:
        """GPU 是否可用。"""
        ...

    @abc.abstractmethod
    def get_gpu_info(self) -> GPUInfo:
        """GPU 信息。"""
        ...

    @abc.abstractmethod
    def get_onnx_providers(self) -> list[str]:
        """返回推荐的 ONNX Runtime execution providers。

        优先级: TensorRT > CUDA > CPU
        """
        ...

    @abc.abstractmethod
    def get_ort_session_options(self) -> dict[str, Any]:
        """ONNX Runtime Session 优化选项。

        返回: kwargs 给 ort.InferenceSession(..., **options)
        """
        ...

    # ────────────────────────────────────────────────────────────────
    # Resource Limits
    # ────────────────────────────────────────────────────────────────

    @abc.abstractmethod
    def get_memory_limit_mb(self) -> int:
        """进程内存上限 (MB)。"""
        ...

    @abc.abstractmethod
    def get_gpu_memory_limit_mb(self) -> int:
        """GPU 显存上限 (MB)。"""
        ...

    @abc.abstractmethod
    def get_cpu_threads(self) -> int:
        """推荐 CPU 线程数。"""
        ...

    @abc.abstractmethod
    def get_worker_count(self) -> int:
        """推荐 worker 数量。"""
        ...

    # ────────────────────────────────────────────────────────────────
    # TTS
    # ────────────────────────────────────────────────────────────────

    @abc.abstractmethod
    def get_tts_engine(self) -> str:
        """TTS 引擎选择。

        返回: 'piper' | 'edge' | 'mock'
        """
        ...

    @abc.abstractmethod
    def get_tts_model_path(self, voice: str) -> Path:
        """TTS 模型路径。"""
        ...

    @abc.abstractmethod
    def supports_fp16_tts(self) -> bool:
        """TTS 是否支持 FP16 推理。"""
        ...

    # ────────────────────────────────────────────────────────────────
    # Avatar
    # ────────────────────────────────────────────────────────────────

    @abc.abstractmethod
    def get_avatar_backend(self) -> str:
        """数字人后端。

        返回: 'wav2lip' | 'sadtalker' | 'mock'
        """
        ...

    @abc.abstractmethod
    def get_avatar_resolution(self) -> tuple[int, int]:
        """数字人分辨率 (width, height)。"""
        ...

    # ────────────────────────────────────────────────────────────────
    # Market Data
    # ────────────────────────────────────────────────────────────────

    @abc.abstractmethod
    def get_market_provider(self) -> str:
        """行情数据源。

        返回: 'akshare' | 'eastmoney' | 'mock'
        """
        ...

    # ────────────────────────────────────────────────────────────────
    # Stream / Output
    # ────────────────────────────────────────────────────────────────

    @property
    @abc.abstractmethod
    def stream_enabled(self) -> bool:
        """是否启用直播推流。Demo 模式返回 False。"""
        ...

    @abc.abstractmethod
    def get_stream_backend(self) -> str:
        """推流后端。

        返回: 'ffmpeg_rtmp' | 'file' | 'mock'
        """
        ...

    # ────────────────────────────────────────────────────────────────
    # Environment Setup
    # ────────────────────────────────────────────────────────────────

    @abc.abstractmethod
    def setup_environment(self) -> None:
        """设置平台特定的环境变量 (OMP, MKL, CUDA, etc.)。"""
        ...

    # ────────────────────────────────────────────────────────────────
    # Config
    # ────────────────────────────────────────────────────────────────

    @abc.abstractmethod
    def get_default_config_paths(self) -> list[str]:
        """默认配置文件路径列表 (优先级从低到高)。"""
        ...

    # ────────────────────────────────────────────────────────────────
    # Safety
    # ────────────────────────────────────────────────────────────────

    @abc.abstractmethod
    def is_safe_to_use_gpu(self) -> bool:
        """GPU 是否安全可用（不掉线，不触发 OOM）。"""
        ...


# ══════════════════════════════════════════════════════════════════════
# Platform Detection
# ══════════════════════════════════════════════════════════════════════

def _detect_jetson() -> bool:
    """检测是否运行在 Jetson 平台。"""
    # 方法 1: 检查 /proc/device-tree/model
    try:
        model_path = "/proc/device-tree/model"
        if os.path.exists(model_path):
            with open(model_path, "r") as f:
                model = f.read().lower()
                if any(k in model for k in ("jetson", "tegra", "xavier", "orin", "nano")):
                    return True
    except Exception:
        pass
    # 方法 2: 检查环境变量
    if os.environ.get("STOCKSTREAM_JETSON_MODE"):
        return True
    # 方法 3: 检查 arch
    if _platform.machine().lower() in ("aarch64", "arm64"):
        try:
            import subprocess
            result = subprocess.run(
                ["dpkg", "-l", "nvidia-l4t-core"],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                return True
        except Exception:
            pass
    return False


def _detect_nvidia_gpu() -> bool:
    """检测是否有 NVIDIA GPU (非 Jetson)。"""
    if _detect_jetson():
        return True  # Jetson 自带 NVIDIA GPU
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except Exception:
        pass
    # Fallback: 尝试 import cupy / numba
    try:
        import cupy
        cupy.cuda.runtime.getDeviceCount()
        return True
    except Exception:
        pass
    return False


def detect_platform(
    force_type: str | None = None,
) -> PlatformInfo:
    """自动检测当前平台并返回 PlatformInfo。

    参数:
        force_type: 强制指定平台类型 ('desktop'|'jetson'|'demo'|'server')
                    用于测试或 Docker 环境。
    """
    if force_type:
        try:
            pt = PlatformType(force_type.lower())
        except ValueError:
            logger.warning("Unknown platform type '%s', auto-detecting", force_type)
            pt = None
    else:
        pt = None

    is_jetson = _detect_jetson()
    has_gpu = _detect_nvidia_gpu()
    is_win = sys.platform == "win32"
    is_linux = sys.platform == "linux"

    # 自动推断
    if pt is None:
        if os.environ.get("STOCKSTREAM_DEMO_MODE"):
            pt = PlatformType.DEMO
        elif is_jetson:
            pt = PlatformType.JETSON
        elif has_gpu and not is_jetson:
            pt = PlatformType.DESKTOP
        elif is_linux:
            pt = PlatformType.SERVER
        else:
            pt = PlatformType.DESKTOP  # 开发机默认

    # Release target mapping
    rt_map = {
        PlatformType.DESKTOP: ReleaseTarget.PRODUCTION_DESKTOP,
        PlatformType.JETSON: ReleaseTarget.PRODUCTION_JETSON,
        PlatformType.DEMO: ReleaseTarget.DEMO,
        PlatformType.SERVER: ReleaseTarget.PRODUCTION_DESKTOP,
    }
    # 开发模式覆盖
    if os.environ.get("STOCKSTREAM_DEV_MODE"):
        rt_map[PlatformType.DESKTOP] = ReleaseTarget.DEV_DESKTOP

    rt = rt_map.get(pt, ReleaseTarget.PRODUCTION_DESKTOP)

    return PlatformInfo(
        platform_type=pt,
        release_target=rt,
        os_name=_platform.system(),
        os_version=_platform.version(),
        python_version=_platform.python_version(),
        arch=_platform.machine().lower(),
        cpu_count=os.cpu_count() or 1,
        is_jetson=is_jetson,
        is_windows=is_win,
        is_linux=is_linux,
        gpu=_get_gpu_info_detailed(pt, is_jetson, has_gpu),
    )


def _get_gpu_info_detailed(
    pt: PlatformType,
    is_jetson: bool,
    has_gpu: bool,
) -> GPUInfo:
    """获取详细 GPU 信息。"""
    info = GPUInfo()

    if pt == PlatformType.DEMO:
        return info

    if is_jetson:
        # Jetson GPU 信息
        try:
            import subprocess
            r = subprocess.run(
                ["tegrastats", "--interval", "0", "--count", "1"],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                # 解析 RAM 使用量，反推总量
                import re
                m = re.search(r"RAM (\d+)/(\d+)MB", r.stdout)
                if m:
                    info.memory_mb = int(m.group(2))
        except Exception:
            pass

        # 获取 CUDA 版本
        try:
            version_path = "/usr/local/cuda/version.txt"
            if os.path.exists(version_path):
                with open(version_path, "r") as f:
                    info.cuda_version = f.read().strip().split()[-1]
        except Exception:
            pass

        # TensorRT 版本
        try:
            import subprocess
            r = subprocess.run(
                ["dpkg", "-l", "tensorrt"],
                capture_output=True, text=True,
            )
            if r.returncode == 0:
                for line in r.stdout.splitlines():
                    if "tensorrt" in line.lower() and "lib" not in line:
                        parts = line.split()
                        if len(parts) >= 3:
                            info.tensorrt_version = parts[2]
        except Exception:
            pass

        info.available = True
        info.name = "Jetson Xavier NX (Volta)"
        info.cuda_compute_capability = "7.2"
        info.fp16_support = True
        info.int8_support = True
        info.memory_mb = info.memory_mb or 8192  # default 8GB

    elif has_gpu:
        import subprocess
        try:
            r = subprocess.run(
                ["nvidia-smi",
                 "--query-gpu=name,memory.total,compute_cap",
                 "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0 and r.stdout.strip():
                parts = r.stdout.strip().split(",")
                if len(parts) >= 1:
                    info.name = parts[0].strip()
                if len(parts) >= 2:
                    try:
                        info.memory_mb = int(parts[1].strip().split()[0])
                    except Exception:
                        pass
        except Exception:
            pass

        # CUDA version via nvcc
        try:
            r = subprocess.run(
                ["nvcc", "--version"],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                import re
                m = re.search(r"release (\d+\.\d+)", r.stdout)
                if m:
                    info.cuda_version = m.group(1)
        except Exception:
            pass

        info.available = True
        info.name = info.name or "NVIDIA GPU"
        info.fp16_support = True
        info.int8_support = True
        info.memory_mb = info.memory_mb or 8192

    return info


# ══════════════════════════════════════════════════════════════════════
# Singleton Adapter
# ══════════════════════════════════════════════════════════════════════

_adapter: PlatformAdapter | None = None


def get_adapter(force_type: str | None = None) -> PlatformAdapter:
    """获取当前平台的适配器单例。

    首次调用自动检测平台。
    可通过 force_type 强制指定类型。
    """
    global _adapter

    if _adapter is not None:
        return _adapter

    info = detect_platform(force_type)
    pt = info.platform_type

    if pt == PlatformType.JETSON:
        from src.platform.jetson import JetsonAdapter
        _adapter = JetsonAdapter()
    elif pt == PlatformType.DEMO:
        from src.platform.demo import DemoAdapter
        _adapter = DemoAdapter()
    elif pt == PlatformType.SERVER:
        from src.platform.server import ServerAdapter
        _adapter = ServerAdapter()
    else:
        from src.platform.desktop import DesktopAdapter
        _adapter = DesktopAdapter()

    _adapter.setup_environment()
    logger.info("Platform adapter: %s", _adapter.get_info().summary())
    return _adapter


def reset_adapter() -> None:
    """重置适配器单例 (用于测试)。"""
    global _adapter
    _adapter = None
