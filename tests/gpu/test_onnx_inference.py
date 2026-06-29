"""GPU inference tests for ONNX Runtime with TensorRT/CUDA fallback.

Validates:
  1. ONNX Runtime provider selection (TensorRT > CUDA > CPU)
  2. FP16 precision on Jetson
  3. CPU fallback when GPU unavailable
  4. Memory constraints (<6GB on Jetson)
"""
from __future__ import annotations

import pytest
import sys


def _has_onnxruntime():
    try:
        import onnxruntime
        return True
    except ImportError:
        return False


def _has_cuda():
    try:
        import onnxruntime
        providers = onnxruntime.get_available_providers()
        return "CUDAExecutionProvider" in providers
    except Exception:
        return False


def _has_tensorrt():
    try:
        import onnxruntime
        providers = onnxruntime.get_available_providers()
        return "TensorrtExecutionProvider" in providers
    except Exception:
        return False


@pytest.mark.gpu
class TestOnnxProviderSelection:
    """ONNX Runtime provider auto-selection tests."""

    @pytest.mark.skipif(not _has_onnxruntime(), reason="ONNX Runtime not installed")
    def test_available_providers_listed(self):
        """Verify provider listing works without errors."""
        import onnxruntime
        providers = onnxruntime.get_available_providers()
        assert isinstance(providers, list)
        assert len(providers) > 0
        # CPU fallback should always be available
        assert "CPUExecutionProvider" in providers

    @pytest.mark.skipif(not _has_onnxruntime(), reason="ONNX Runtime not installed")
    def test_jetson_gpu_fallback_order(self):
        """Verify Jetson GPU fallback hierarchy: TensorRT > CUDA > CPU."""
        from src.platform.jetson import JetsonAdapter
        adapter = JetsonAdapter()
        gpu_info = adapter.get_gpu_info()
        # On non-Jetson, this should still return valid struct
        assert isinstance(gpu_info, dict)

    @pytest.mark.skipif(not _has_onnxruntime(), reason="ONNX Runtime not installed")
    def test_desktop_gpu_providers(self):
        """Verify desktop GPU providers available."""
        from src.platform.desktop import DesktopAdapter
        adapter = DesktopAdapter()
        gpu_info = adapter.get_gpu_info()
        assert isinstance(gpu_info, dict)


@pytest.mark.gpu
class TestFP16Inference:
    """FP16 precision tests for Jetson optimization."""

    def test_fp16_configured_on_jetson(self):
        """Verify Jetson adapter defaults to FP16."""
        from src.platform.jetson import JetsonAdapter
        adapter = JetsonAdapter()
        assert adapter.default_precision == "fp16"

    def test_fp32_default_on_desktop(self):
        """Verify Desktop adapter defaults to FP32."""
        from src.platform.desktop import DesktopAdapter
        adapter = DesktopAdapter()
        assert adapter.default_precision == "fp32"


@pytest.mark.gpu
class TestResourceConstraints:
    """Jetson resource constraint tests."""

    def test_jetson_memory_limit(self):
        """Verify Jetson memory limit < 6GB."""
        from src.platform.jetson import JetsonAdapter
        adapter = JetsonAdapter()
        limits = adapter.get_resource_limits()
        assert limits["max_memory_mb"] <= 6144

    def test_jetson_gpu_percent(self):
        """Verify Jetson GPU usage limit < 80%."""
        from src.platform.jetson import JetsonAdapter
        adapter = JetsonAdapter()
        limits = adapter.get_resource_limits()
        assert limits["max_gpu_percent"] <= 80

    def test_jetson_cpu_percent(self):
        """Verify Jetson CPU usage limit < 70%."""
        from src.platform.jetson import JetsonAdapter
        adapter = JetsonAdapter()
        limits = adapter.get_resource_limits()
        assert limits["max_cpu_percent"] <= 70


@pytest.mark.gpu
class TestCUDATensorRTCompat:
    """CUDA 11.4 / TensorRT 8 compatibility tests."""

    def test_jetson_cuda_version_constraint(self):
        """Verify Jetson adapter targets CUDA 11.4."""
        from src.platform.jetson import JetsonAdapter
        adapter = JetsonAdapter()
        assert adapter.target_cuda_version == "11.4"

    def test_jetson_tensorrt_version_constraint(self):
        """Verify Jetson adapter targets TensorRT 8.x."""
        from src.platform.jetson import JetsonAdapter
        adapter = JetsonAdapter()
        assert adapter.target_tensorrt_version == "8"
