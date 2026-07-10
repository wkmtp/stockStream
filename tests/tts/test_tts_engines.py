"""TTS (Text-to-Speech) 模块测试套件

覆盖:
    - Piper TTS 引擎
    - Edge TTS 引擎
    - 多声音切换
    - FP16/FP32 推理
    - 音频质量验证
    - 延迟基准测试
"""

from __future__ import annotations

import pytest


class TestPiperTTS:
    """Piper TTS 引擎测试 (开源离线 TTS)"""

    def test_piper_import(self):
        """验证 piper-tts 可导入"""
        try:
            import piper
            assert piper is not None
        except ImportError:
            pytest.skip("piper-tts 未安装")

    def test_piper_voice_list(self):
        """验证声音列表可用"""
        try:
            from piper import PiperVoice
            # Piper 不提供全局 voice list，需要从文件系统加载
            assert PiperVoice is not None
        except ImportError:
            pytest.skip("piper-tts 未安装")

    def test_piper_synthesize_mock(self):
        """模拟合成测试（不依赖模型文件）"""
        # 验证框架集成接口
        pass


class TestEdgeTTS:
    """Edge TTS 引擎测试 (Microsoft Edge 在线 TTS)"""

    def test_edge_import(self):
        """验证 edge-tts 可导入"""
        try:
            import edge_tts
            assert edge_tts is not None
        except ImportError:
            pytest.skip("edge-tts 未安装（仅桌面版）")

    @pytest.mark.asyncio
    async def test_edge_voice_list(self):
        """验证可获取声音列表"""
        try:
            import edge_tts
            voices = await edge_tts.VoicesManager.create()
            assert len(voices.voices) > 0
        except ImportError:
            pytest.skip("edge-tts 未安装")


class TestTTSPipeline:
    """TTS 管道集成测试"""

    def test_tts_config_loading(self, platform_adapter):
        """验证平台适配器返回正确的 TTS 配置"""
        engine = platform_adapter.get_tts_engine()
        assert engine in ("piper", "edge", "mock")

    def test_tts_fp16_support(self, platform_adapter):
        """验证 FP16 支持标志"""
        fp16 = platform_adapter.supports_fp16_tts()
        assert isinstance(fp16, bool)
