"""Dual-voice TTS — separate male/female voice synthesis with emotion control.

Extends the existing TTSService to support two distinct voices (male veteran,
female newcomer) with emotion-driven speech parameters.

Key design: male voice uses piper's zh_CN-chaowen-medium (男声), female voice
uses zh_CN-huayan-medium (女声).  True dual-voice separation is achieved via
different ONNX model files rather than mere parameter modulation, giving each
speaker a genuinely distinct timbre and vocal quality.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import TYPE_CHECKING

from stockstream.dual_host.models import (
    DialogTurn,
    Emotion,
    Speaker,
)
from stockstream.tts.models import TTSVoice

if TYPE_CHECKING:
    from stockstream.tts.service import TTSService

logger = logging.getLogger(__name__)

# ── Piper voice models ──────────────────────────────────────────
# Separate ONNX files for male vs female voices — each produces a
# genuinely different timbre, not just speed/prosody adjustments.
# Download: python scripts/download_models.py --tts
MALE_PIPER_MODEL = "zh_CN-chaowen-medium"      # 男声 - 超文
FEMALE_PIPER_MODEL = "zh_CN-huayan-medium"      # 女声 - 华燕


# ── Emotion → Piper parameter modulation ───────────────────────

# Maps emotion → (length_scale, noise_scale, noise_w) adjustments
# length_scale: < 1.0 = faster speech
# noise_scale: higher = more expressive/varied

EMOTION_VOICE_PARAMS: dict[Emotion, tuple[float, float, float]] = {
    Emotion.NEUTRAL:   (1.00, 0.667, 0.80),
    Emotion.HAPPY:     (0.95, 0.700, 0.75),   # slightly faster, lighter
    Emotion.EXCITED:   (0.88, 0.750, 0.70),   # faster, more expressive
    Emotion.SERIOUS:   (1.05, 0.600, 0.85),   # slower, weightier
    Emotion.SURPRISED: (0.90, 0.720, 0.72),   # quick, emphatic
    Emotion.WARNING:   (1.08, 0.580, 0.88),   # slower, grave
    Emotion.THINKING:  (1.10, 0.650, 0.82),   # drawn out, thoughtful
    Emotion.HUMOROUS:  (0.92, 0.730, 0.70),   # playful
}


# ── Character voice presets ────────────────────────────────────

# Male: 资深股民 — uses zh_CN-chaowen-medium (超文, male timbre)
# Deeper, confident delivery via moderate length_scale and low noise_w.
MALE_VOICE_PRESET = TTSVoice(
    name=MALE_PIPER_MODEL,
    model_path=f"models/{MALE_PIPER_MODEL}.onnx",
    length_scale=1.05,
    noise_scale=0.65,
    noise_w=0.78,
    sentence_silence=0.28,
)

# Female: 财经新人 — uses zh_CN-huayan-medium (华燕, female timbre)
# Lighter, lively delivery with shorter pauses and brighter modulation.
FEMALE_VOICE_PRESET = TTSVoice(
    name=FEMALE_PIPER_MODEL,
    model_path=f"models/{FEMALE_PIPER_MODEL}.onnx",
    length_scale=0.92,
    noise_scale=0.72,
    noise_w=0.72,
    sentence_silence=0.16,
)


class DualVoiceTTS:
    """Manages two TTS instances for male and female hosts.

    Each speaker gets a corresponding voice preset and emotion-driven
    parameter modulation for natural-sounding dialogue.
    """

    male_voice: TTSVoice
    female_voice: TTSVoice
    output_dir: str
    inter_speaker_pause: float

    def __init__(
        self,
        *,
        tts_svc: TTSService,
        male_voice: TTSVoice | None = None,
        female_voice: TTSVoice | None = None,
        output_dir: str = "data/dual_host_audio",
        inter_speaker_pause: float = 0.5,
    ) -> None:
        self.tts: TTSService = tts_svc
        self.tts = tts_svc
        self.male_voice = male_voice or MALE_VOICE_PRESET
        self.female_voice = female_voice or FEMALE_VOICE_PRESET
        self.output_dir = output_dir
        self.inter_speaker_pause = inter_speaker_pause
        os.makedirs(output_dir, exist_ok=True)

    # ── public API ──────────────────────────────────────────────

    async def speak_turn(self, turn: DialogTurn) -> dict[str, object]:
        """Synthesise a single dialog turn with emotion-adjusted voice.

        The modulated voice parameters (length_scale, noise_scale, noise_w,
        sentence_silence) now flow through TTSService -> PiperEngine -> piper CLI,
        producing distinct male/female voice characteristics.

        Uses text_to_wav directly to bypass the worker queue (which requires
        initialize() + event loop).  Each turn is a short sentence so the
        direct call is appropriate.

        Args:
            turn: A DialogTurn with speaker, text, and emotion.

        Returns:
            Dict with task_id, speaker, voice metadata, and wav info.
        """
        voice = self.male_voice if turn.speaker == Speaker.MALE else self.female_voice
        voice = self._modulate_voice(voice, turn.emotion)

        # Direct synthesis — bypasses worker queue for per-turn control
        wav_path = await self.tts.text_to_wav(turn.text, voice=voice)
        return {
            "task_id": str(uuid.uuid4().hex[:8]),
            "speaker": turn.speaker.value,
            "emotion": turn.emotion.value,
            "text": turn.text,
            "sentence_count": 1,
            "wav_paths": [wav_path] if wav_path else [],
            "voice_name": voice.name,
            "model_path": voice.model_path,
            "length_scale": voice.length_scale,
            "noise_scale": voice.noise_scale,
            "noise_w": voice.noise_w,
        }

    async def speak_script(self, turns: list[DialogTurn]) -> list[dict[str, object]]:
        """Synthesise an entire dialogue script sequentially.

        Args:
            turns: Ordered list of DialogTurn.

        Returns:
            List of result dicts for each turn.
        """
        results: list[dict[str, object]] = []
        prev_speaker: Speaker | None = None
        for turn in turns:
            if not turn.text.strip():
                continue
            result = await self.speak_turn(turn)
            results.append(result)

            # Natural pause between speakers for realistic dialogue rhythm
            if prev_speaker is not None and prev_speaker != turn.speaker:
                await asyncio.sleep(self.inter_speaker_pause)
            else:
                await asyncio.sleep(0.15)

            prev_speaker = turn.speaker

        return results

    async def speak_and_wait(self, turns: list[DialogTurn],
                             timeout: float = 120.0) -> list[dict[str, object]]:
        """Synthesise all turns sequentially and return results.

        Uses ``speak_turn`` for each turn — same code path as
        ``speak_script`` but without inter-speaker pauses.
        """
        results: list[dict[str, object]] = []
        for turn in turns:
            if not turn.text.strip():
                continue
            try:
                result = await asyncio.wait_for(
                    self.speak_turn(turn), timeout=timeout,
                )
                results.append(result)
            except asyncio.TimeoutError:
                results.append({"error": f"Timeout for {turn.speaker.value}"})
            except Exception as exc:
                results.append({"error": str(exc)})
        return results

    async def text_to_wav(self, text: str, speaker: Speaker,
                          emotion: Emotion = Emotion.NEUTRAL) -> str:
        """Quick synthesis for short text directly to WAV.

        Now correctly passes emotion-modulated voice parameters through
        TTSService → PiperEngine → piper CLI for true dual-voice output.
        """
        voice = self.male_voice if speaker == Speaker.MALE else self.female_voice
        voice = self._modulate_voice(voice, emotion)
        return await self.tts.text_to_wav(text, voice=voice)

    # ── voice modulation ────────────────────────────────────────

    def _modulate_voice(self, base: TTSVoice, emotion: Emotion) -> TTSVoice:
        """Apply emotion-driven parameter adjustments to a voice.

        IMPORTANT: model_path, name, config_path, and sample_rate are
        propagated from the base voice so PiperEngine can locate the ONNX
        model.  Only the synthesis parameters (length/noise/noise_w) are
        modulated; the model file is the same for all voices.
        """
        params = EMOTION_VOICE_PARAMS.get(emotion, EMOTION_VOICE_PARAMS[Emotion.NEUTRAL])
        return TTSVoice(
            name=base.name,
            model_path=base.model_path,
            config_path=base.config_path,
            sample_rate=base.sample_rate,
            length_scale=base.length_scale * params[0],
            noise_scale=base.noise_scale * params[1],
            noise_w=base.noise_w * params[2],
            sentence_silence=base.sentence_silence,
        )
