"""Piper TTS engine — local neural text-to-speech via subprocess.

Supports two backends:
    1. piper CLI   (subprocess) — zero Python deps, best for Jetson
    2. piper-tts   (Python lib) — faster in-process, needs pip install piper-tts

Usage::

    engine = PiperEngine(voice=TTSVoice(model_path="zh_CN-huayan-medium.onnx"))
    wav_path = await engine.text_to_wav("贵州茅台今日上涨2.35%。")
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import time as _time
import uuid
from pathlib import Path

from typing import Any

# ── 24h 稳定性常量 ──
_TTS_CACHE_MAX_AGE_HOURS = 24   # WAV 缓存最长保留 24 小时
_TTS_CACHE_MAX_FILES = 1000     # 缓存文件数上限（防止 inode 耗尽）

from stockstream.tts.models import TTSVoice

logger = logging.getLogger(__name__)

# Fallback voice model name — user should download from:
# https://huggingface.co/rhasspy/piper-voices
_DEFAULT_MODEL = "zh_CN-huayan-medium"

# Try Python bindings first, then CLI
_py_piper_ok: bool = False
_piper_cli_path: str | None = None

try:
    from piper.voice import PiperVoice  # type: ignore[import-untyped]

    _py_piper_ok = True
except ImportError:
    pass

if not _py_piper_ok:
    _piper_cli_path = shutil.which("piper") or ""
    if _piper_cli_path:
        logger.info("Using piper CLI at %s", _piper_cli_path)
    else:
        logger.warning(
            "Piper not found — install 'pip install piper-tts' or download the "
            + "piper binary from https://github.com/rhasspy/piper/releases"
        )


class PiperEngine:
    """Local neural TTS engine using Piper.

    Auto-detects available backend (Python bindings > CLI).  Falls back
    gracefully when neither is installed — all methods return empty results
    so downstream code does not crash.
    """

    voice: TTSVoice
    _py_voice: Any | None  # pyright: ignore[reportExplicitAny]
    _ready: bool

    def __init__(self, voice: TTSVoice | None = None) -> None:
        self.voice = voice or TTSVoice()
        self._py_voice = None  # PiperVoice instance
        self._ready = False
        self._wav_count = 0     # 24h stability: track WAVs produced this session

    async def initialize(self) -> None:
        """Load the voice model (Python bindings path only)."""
        # 24h: 幂等性保护 — 防止重复加载导致内存泄漏
        if self._ready:
            return

        if not _py_piper_ok and not _piper_cli_path:
            logger.info("PiperEngine: no backend available (dry-run mode)")
            self._ready = True
            return

        if _py_piper_ok:
            await self._init_python_backend()
        else:
            await self._init_cli_backend()

        self._ready = True

    async def _init_python_backend(self) -> None:
        """Load PiperVoice via Python bindings."""
        model_path = self._resolve_model()
        if not os.path.isfile(model_path):
            logger.warning(
                "Voice model not found: %s — download it from "
                + "https://huggingface.co/rhasspy/piper-voices", model_path
            )
            return
        try:
            self._py_voice = PiperVoice.load(model_path)  # type: ignore[name-defined]  # pyright: ignore[reportPossiblyUnboundVariable]
            logger.info("Piper Python backend loaded: %s", model_path)
        except Exception as exc:
            logger.error("Failed to load Piper voice model: %s", exc)

    async def _init_cli_backend(self) -> None:
        """Verify piper CLI is callable."""
        if not _piper_cli_path:
            return
        try:
            proc = await asyncio.create_subprocess_exec(
                _piper_cli_path, "--help",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            _ = await proc.wait()
            if proc.returncode == 0:
                logger.info("Piper CLI backend verified")
            else:
                logger.warning("Piper CLI returned %d", proc.returncode)
        except FileNotFoundError:
            logger.warning("Piper CLI not found at %s", _piper_cli_path)

    # ── public API ───────────────────────────────────────────────────

    async def text_to_wav(
        self,
        text: str,
        *,
        voice: TTSVoice | None = None,
        output_dir: str | None = None,
    ) -> str:
        """Synthesise text into a WAV file.

        Args:
            text: Text to synthesise (short sentence, ideally ≤60 chars).
            voice: Optional per-call voice override (length_scale, noise_scale,
                   noise_w, sentence_silence applied to synthesis).
            output_dir: Directory to write the WAV file to (default: temp dir).

        Returns:
            Absolute path to the WAV file, or empty string on failure.
        """
        if not text or not text.strip():
            return ""

        if not self._ready:
            await self.initialize()

        active_voice = voice or self.voice

        out_dir = Path(output_dir) if output_dir else Path(tempfile.gettempdir()) / "stockstream_tts"
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4().hex[:12]}.wav"
        out_path = out_dir / filename

        # 24h 稳定性：每生成 50 个 WAV 后触发一次缓存清理
        self._wav_count += 1
        if self._wav_count % 50 == 0:
            await asyncio.to_thread(_cleanup_tts_cache, str(out_dir))

        # Try Python bindings first
        if self._py_voice is not None:
            return await self._synthesize_python(text, str(out_path), active_voice)

        # Fall back to CLI
        if _piper_cli_path:
            return await self._synthesize_cli(text, str(out_path), active_voice)

        logger.debug("No Piper backend — text not synthesized: %s", text[:50])
        return ""

    async def synthesize_stream(
        self,
        text: str,
        *,
        voice: TTSVoice | None = None,
    ) -> bytes:
        """Synthesise to raw PCM bytes for streaming (CLI mode only).

        Returns raw 16-bit signed PCM at voice sample rate, or empty bytes.
        """
        if not text or not text.strip() or not _piper_cli_path:
            return b""

        active_voice = voice or self.voice
        model = self._resolve_model_for_voice(active_voice)
        args = [
            _piper_cli_path, "--model", model, "--output-raw",
            "--length_scale", str(active_voice.length_scale),
            "--noise_scale", str(active_voice.noise_scale),
            "--noise_w", str(active_voice.noise_w),
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=text.encode("utf-8")),
                timeout=10.0,
            )
            if proc.returncode != 0:
                logger.error("Piper stream error: %s", stderr.decode(errors="replace"))
                return b""
            return stdout
        except asyncio.TimeoutError:
            logger.error("Piper stream timed out for %d chars", len(text))
            # 24h: 超时后必须 kill 子进程，防止僵尸进程累积
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            return b""
        except Exception as exc:
            logger.error("Piper stream exception: %s", exc)
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            return b""

    # ── internal ─────────────────────────────────────────────────────

    async def _synthesize_python(self, text: str, out_path: str, voice: TTSVoice | None = None) -> str:  # pyright: ignore[reportUnusedParameter]
        """Use Piper Python bindings to write WAV.

        Note: Python PiperVoice.synthesize() does not support per-call
        length_scale/noise_scale modulation — those are baked into the model
        at load time.  For dynamic voice control, use the CLI backend.
        """
        try:
            pv: Any = self._py_voice  # pyright: ignore[reportExplicitAny]
            loop = asyncio.get_running_loop()
            raw = await loop.run_in_executor(
                None,
                lambda: _py_synth_to_wav(pv, text, out_path),
            )
            return out_path if raw else ""
        except Exception as exc:
            logger.error("Python Piper synthesis failed: %s", exc)
            return ""

    async def _synthesize_cli(self, text: str, out_path: str, voice: TTSVoice) -> str:
        """Use piper CLI subprocess to write WAV with full voice modulation.

        Passes length_scale, noise_scale, noise_w, and sentence_silence to the
        piper binary so that DualVoiceTTS emotion modulation takes effect.
        """
        model = self._resolve_model_for_voice(voice)
        args = [
            _piper_cli_path or "piper",
            "--model", model,
            "--output_file", out_path,
            "--length_scale", str(voice.length_scale),
            "--noise_scale", str(voice.noise_scale),
            "--noise_w", str(voice.noise_w),
            "--sentence_silence", str(voice.sentence_silence),
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(
                proc.communicate(input=text.encode("utf-8")),
                timeout=10.0,
            )
            if proc.returncode != 0:
                logger.error("Piper CLI error (rc=%d): %s",
                             proc.returncode, stderr.decode(errors="replace"))
                return ""
            return out_path
        except asyncio.TimeoutError:
            logger.error("Piper CLI timed out for %d chars", len(text))
            # 24h: 超时后必须 kill 子进程，防止僵尸进程累积
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            return ""
        except FileNotFoundError:
            logger.error("Piper binary not found: %s", _piper_cli_path)
            return ""
        except Exception as exc:
            logger.error("Piper CLI exception: %s", exc)
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            return ""

    def _resolve_model(self) -> str:
        """Return the model path to use from the default voice."""
        return self._resolve_model_for_voice(self.voice)

    def _resolve_model_for_voice(self, voice: TTSVoice) -> str:
        """Return the model path for a specific TTSVoice configuration."""
        if voice.model_path and os.path.isfile(voice.model_path):
            return voice.model_path
        # Try common locations
        candidates = [
            voice.model_path,
            voice.name + ".onnx",
            os.path.join("models", voice.name + ".onnx"),
            os.path.join("/usr/share/piper-tts", voice.name + ".onnx"),
        ]
        for c in candidates:
            if c and os.path.isfile(c):
                return c
        # Return the name so CLI can search $PIPER_MODEL_DIR
        return voice.name

    def available(self) -> bool:
        """Return True if any synthesis backend is available."""
        return _py_piper_ok or bool(_piper_cli_path)

    @staticmethod
    def cleanup_cache(output_dir: str | None = None) -> int:
        """清理过期的 TTS WAV 缓存文件。返回删除的文件数。

        24h 稳定性：防止 WAV 文件堆积导致磁盘满。
        """
        target = Path(output_dir) if output_dir else Path(tempfile.gettempdir()) / "stockstream_tts"
        return _cleanup_tts_cache(str(target))


# ── Python-bindings helper ────────────────────────────────────────────


def _py_synth_to_wav(voice: Any, text: str, out_path: str) -> bool:  # pyright: ignore[reportExplicitAny, reportAny]
    """Run synthesis via PiperVoice and write WAV file (sync, runs in executor)."""
    import wave
    import io

    try:
        raw_buffer = io.BytesIO()
        voice.synthesize(text, raw_buffer)  # pyright: ignore[reportAny]
        _ = raw_buffer.seek(0)

        # PiperVoice.synthesize writes raw PCM; wrap as WAV
        with wave.open(out_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(voice.config.sample_rate)  # pyright: ignore[reportAny]
            wf.writeframes(raw_buffer.read())

        return True
    except Exception as exc:
        logger.error("_py_synth_to_wav failed: %s", exc)
        return False


# ── 24h 稳定性: TTS 缓存清理 ──────────────────────────────────────


def _cleanup_tts_cache(dir_path: str) -> int:
    """同步清理过期的 WAV 缓存文件（在 asyncio.to_thread 中运行）。"""
    import os as _sync_os
    target = Path(dir_path)
    if not target.is_dir():
        return 0

    now = _time.time()
    max_age = _TTS_CACHE_MAX_AGE_HOURS * 3600
    removed = 0

    try:
        files = sorted(target.glob("*.wav"), key=lambda p: p.stat().st_mtime)
        for f in files:
            age = now - f.stat().st_mtime
            # 超过最大保留时间或超出文件数上限
            if age > max_age or len(files) - removed > _TTS_CACHE_MAX_FILES:
                try:
                    _sync_os.unlink(f)
                    removed += 1
                except OSError:
                    pass
            elif age <= max_age and len(files) - removed <= _TTS_CACHE_MAX_FILES:
                break  # 剩下的文件都在有效期内且未超限
    except Exception:
        logger.debug("TTS cache cleanup failed for %s", dir_path)

    if removed:
        logger.debug("TTS cache cleaned: %d WAVs removed from %s", removed, dir_path)
    return removed
