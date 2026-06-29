"""平台适配层 — V4.0 Enterprise Edition

采用 Adapter Pattern，隔离所有平台差异。
业务代码通过此层访问平台能力，禁止直接判断操作系统/硬件。

适配器自动检测当前平台:
    - DesktopAdapter   (x86_64, 有 RTX GPU, Python 3.10+)
    - JetsonAdapter    (ARM64, JetPack 5.x, Python 3.8)
    - DemoAdapter      (任意平台, 模拟行情/互动, 无需外部服务)
    - ServerAdapter    (Linux Server, CPU-only 推理)
"""

from src.platform.base import (
    PlatformAdapter,
    PlatformType,
    GPUInfo,
    PlatformInfo,
    detect_platform,
    get_adapter,
)

__all__ = [
    "PlatformAdapter",
    "PlatformType",
    "GPUInfo",
    "PlatformInfo",
    "detect_platform",
    "get_adapter",
]
