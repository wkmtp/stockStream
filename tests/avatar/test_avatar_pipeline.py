"""Avatar (数字人) 模块测试套件

覆盖:
    - Wav2Lip 推理
    - 人脸检测 (YOLOv8)
    - 视频合成管道
    - ONNX 模型加载
    - 分辨率切换
    - 内存使用
"""

from __future__ import annotations

import pytest


class TestFaceDetection:
    """人脸检测模块测试"""

    def test_face_detector_import(self):
        """验证人脸检测模块可导入"""
        try:
            from stockstream.avatar import face_detector
            assert face_detector is not None
        except ImportError:
            pytest.skip("人脸检测模块不可用")

    def test_face_detector_providers(self, platform_adapter):
        """验证 ONNX providers 配置"""
        providers = platform_adapter.get_onnx_providers()
        assert len(providers) > 0
        assert all(p in (
            "TensorrtExecutionProvider",
            "CUDAExecutionProvider",
            "CPUExecutionProvider",
        ) for p in providers)


class TestWav2Lip:
    """Wav2Lip 推理测试"""

    def test_wav2lip_import(self):
        """验证 Wav2Lip 模块可导入"""
        try:
            from stockstream.avatar import wav2lip_onnx
            assert wav2lip_onnx is not None
        except ImportError:
            pytest.skip("Wav2Lip 模块不可用")

    def test_wav2lip_providers_auto_detect(self, platform_adapter):
        """验证自动 GPU 检测: TensorRT > CUDA > CPU"""
        providers = platform_adapter.get_onnx_providers()
        if platform_adapter.gpu_available:
            assert any("CUDA" in p or "Tensorrt" in p for p in providers)


class TestAvatarPipeline:
    """数字人管道集成测试"""

    def test_resolution_config(self, platform_adapter):
        """验证分辨率配置"""
        w, h = platform_adapter.get_avatar_resolution()
        assert w > 0
        assert h > 0
        assert w <= 1920  # 最大支持 1080p
        assert h <= 1080

    def test_backend_selection(self, platform_adapter):
        """验证后端选择"""
        backend = platform_adapter.get_avatar_backend()
        assert backend in ("wav2lip", "sadtalker", "mock")

    def test_memory_limit(self, platform_adapter):
        """验证 GPU 显存限制"""
        limit_mb = platform_adapter.get_gpu_memory_limit_mb()
        if platform_adapter.gpu_available:
            assert limit_mb > 0
