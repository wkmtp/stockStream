"""Jetson Xavier NX 优化模块 — TensorRT FP16 推理 + 内存管理 + 资源调度。

目标:
  - 内存占用 < 6GB
  - GPU 占用 < 80%
  - TensorRT FP16 加速
  - 批量推理优化
"""

from __future__ import annotations

import gc
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class JetsonOptimizer:
    """Jetson Xavier NX 资源优化器。

    功能:
        - 定期内存回收
        - GPU 显存监控
        - TensorRT 引擎管理
        - CPU 亲和性设置
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self._cfg = config or {}
        self._jetson_mode = self._cfg.get("jetson_mode", bool(os.environ.get("STOCKSTREAM_JETSON_MODE")))
        self._memory_limit_mb = self._cfg.get("memory_limit_mb", 5800)
        self._gpu_limit_pct = self._cfg.get("gpu_limit_pct", 80)
        self._tensorrt_fp16 = self._cfg.get("tensorrt_fp16", True)
        self._onnx_threads = self._cfg.get("onnx_threads", 4)
        self._gc_interval = self._cfg.get("gc_interval", 60.0)
        self._last_gc = 0.0

        if self._jetson_mode:
            self._apply_jetson_defaults()

    def _apply_jetson_defaults(self) -> None:
        """应用 Jetson Xavier NX 环境变量优化。"""
        # 限制 OpenMP/MKL 线程数
        os.environ.setdefault("OMP_NUM_THREADS", str(self._onnx_threads))
        os.environ.setdefault("MKL_NUM_THREADS", str(self._onnx_threads))
        os.environ.setdefault("OPENBLAS_NUM_THREADS", str(self._onnx_threads))
        os.environ.setdefault("VECLIB_MAXIMUM_THREADS", str(self._onnx_threads))
        os.environ.setdefault("NUMEXPR_NUM_THREADS", str(self._onnx_threads))

        # ONNX Runtime 选项
        os.environ.setdefault("ORT_TENSORRT_FP16_ENABLE", "1" if self._tensorrt_fp16 else "0")
        os.environ.setdefault("ORT_TENSORRT_ENGINE_CACHE_ENABLE", "1")
        os.environ.setdefault("ORT_TENSORRT_MAX_WORKSPACE_SIZE", "2147483648")  # 2GB (Xavier NX 安全值)

        logger.info(
            "Jetson Xavier NX optimized: threads=%d, TensorRT_FP16=%s, mem_limit=%dMB",
            self._onnx_threads, self._tensorrt_fp16, self._memory_limit_mb,
        )

    async def maybe_gc(self, force: bool = False) -> None:
        """按需执行垃圾回收 (仅当间隔超过 gc_interval 或强制时)。"""
        now = time.monotonic()
        if force or (now - self._last_gc > self._gc_interval):
            gc.collect()
            self._last_gc = now

    def get_memory_stats(self) -> dict[str, Any]:
        """获取当前内存使用统计。"""
        try:
            import psutil
            proc = psutil.Process(os.getpid())
            mem = proc.memory_info()
        except ImportError:
            return {"rss_mb": -1, "vms_mb": -1, "pct": -1}

        return {
            "rss_mb": round(mem.rss / 1024 / 1024, 1),
            "vms_mb": round(mem.vms / 1024 / 1024, 1),
            "pct": round(proc.memory_percent(), 1),
            "limit_mb": self._memory_limit_mb,
            "healthy": mem.rss / 1024 / 1024 < self._memory_limit_mb,
        }

    def get_gpu_stats(self) -> dict[str, Any]:
        """V3.0: 获取 GPU 使用统计。
        优先 tegrastats (Jetson)，回退 nvidia-smi (通用 NVIDIA)，
        最后尝试 /sys/devices/gpu.0/load。
        """
        result = self._try_tegrastats()
        if result["gpu_available"]:
            return result
        result = self._try_nvidia_smi()
        if result["gpu_available"]:
            return result
        return self._try_sysfs()

    def _try_tegrastats(self) -> dict[str, Any]:
        """通过 tegrastats 获取 Jetson GPU 统计。"""
        try:
            import subprocess
            result = subprocess.run(
                ["tegrastats", "--interval", "100", "--count", "1"],
                capture_output=True, text=True, timeout=5,
            )
            output = result.stdout
            gpu_pct = 0.0
            ram_mb = 0

            if "GR3D_FREQ" in output:
                # V3.0: 正确解析 GR3D_FREQ <freq>%@<value> 格式
                # tegrastats 输出类似: GR3D_FREQ 50%@<freq>
                import re
                gpu_match = re.search(r'GR3D_FREQ\s+(\d+)%', output)
                if gpu_match:
                    gpu_pct = float(gpu_match.group(1))

                for part in output.split():
                    if part.startswith("RAM"):
                        try:
                            used_str = part.split("/")[0].replace("RAM", "")
                            ram_mb = int(used_str.replace("MB", ""))
                        except (ValueError, IndexError):
                            pass
            return {
                "gpu_available": True,
                "ram_used_mb": ram_mb,
                "gpu_pct_est": gpu_pct,
                "healthy": ram_mb < 5500,
                "source": "tegrastats",
            }
        except Exception:
            return {"gpu_available": False, "error": "tegrastats not available"}

    def _try_nvidia_smi(self) -> dict[str, Any]:
        """V3.0: 通过 nvidia-smi 获取 NVIDIA GPU 统计（非 Jetson 环境）。"""
        try:
            import subprocess
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return {"gpu_available": False}
            parts = [p.strip() for p in result.stdout.strip().split(",")]
            if len(parts) >= 4:
                gpu_pct = float(parts[0]) if parts[0] != "[Not Supported]" else 0.0
                mem_used = float(parts[1])
                mem_total = float(parts[2])
                temp_c = float(parts[3]) if parts[3] != "[Not Supported]" else 0.0
                return {
                    "gpu_available": True,
                    "gpu_pct_est": gpu_pct,
                    "ram_used_mb": mem_used,
                    "ram_total_mb": mem_total,
                    "temperature_c": temp_c,
                    "healthy": gpu_pct < 90.0 and mem_used / max(mem_total, 1) < 0.9,
                    "source": "nvidia-smi",
                }
            return {"gpu_available": False}
        except Exception:
            return {"gpu_available": False, "error": "nvidia-smi not available"}

    def _try_sysfs(self) -> dict[str, Any]:
        """V3.0: 通过 /sys/devices/gpu.0/load 获取 GPU 负载（Linux 通用）。"""
        gpu_load = "/sys/devices/gpu.0/load"
        if os.path.exists(gpu_load):
            try:
                with open(gpu_load) as f:
                    utilization = float(f.read().strip()) / 10.0
                return {
                    "gpu_available": True,
                    "gpu_pct_est": utilization,
                    "healthy": utilization < 90.0,
                    "source": "sysfs",
                }
            except (OSError, ValueError):
                pass
        return {"gpu_available": False, "error": "no GPU metrics source available"}

    def get_optimization_status(self) -> dict[str, Any]:
        """返回优化器完整状态。"""
        return {
            "jetson_mode": self._jetson_mode,
            "tensorrt_fp16": self._tensorrt_fp16,
            "onnx_threads": self._onnx_threads,
            "memory_limit_mb": self._memory_limit_mb,
            "gpu_limit_pct": self._gpu_limit_pct,
            "memory": self.get_memory_stats(),
            "gpu": self.get_gpu_stats(),
        }


# 全局单例
_jetson_optimizer: JetsonOptimizer | None = None


def get_jetson_optimizer() -> JetsonOptimizer:
    """获取全局 Jetson 优化器实例。"""
    global _jetson_optimizer
    if _jetson_optimizer is None:
        _jetson_optimizer = JetsonOptimizer()
    return _jetson_optimizer
