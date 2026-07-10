"""Future TensorRT integration seam.

Keep TensorRT imports out of module import paths until enabled on Jetson, because
TensorRT wheels are provided by NVIDIA JetPack and are platform specific.
"""

from stockstream.core.config import get_settings


class TensorRTRuntime:
    """Lazy TensorRT runtime placeholder."""

    def __init__(self) -> None:
        self.enabled = get_settings().tensorrt_enabled

    def available(self) -> bool:
        """Return whether TensorRT has been enabled in configuration."""

        return self.enabled
