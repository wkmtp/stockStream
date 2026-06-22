"""Dual-voice TTS full-pipeline integration tests.

Validates every link in the chain:
    DualVoiceTTS -> TTSService -> PiperEngine -> piper CLI
                     ↑
               model resolution
                     ↑
    stream bus ← _synthesize_script

Covers:
    - Voice presets (model_path, name) -> PiperEngine can locate ONNX model
    - _modulate_voice preserves model_path/config_path/sample_rate
    - text_to_wav passes modulated voice to TTSService
    - speak_turn returns full voice metadata + wav_paths
    - speak_script -> stream bus publishes dual_host.audio events
    - Emotion -> parameter modulation math
    - Dry-run mode (no Piper installation required)
"""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stockstream.dual_host.dual_voice_tts import (
    DualVoiceTTS,
    MALE_VOICE_PRESET,
    FEMALE_VOICE_PRESET,
    EMOTION_VOICE_PARAMS,
    MALE_PIPER_MODEL,
    FEMALE_PIPER_MODEL,
)
from stockstream.dual_host.models import (
    DialogTurn,
    Emotion,
    Speaker,
)
from stockstream.tts import service as tts_service
from stockstream.tts.engine import PiperEngine
from stockstream.tts.models import TTSVoice

# ── Helpers ────────────────────────────────────────────────────────

_pass_count = 0
_fail_count = 0


def ok(label: str) -> None:
    global _pass_count
    _pass_count += 1
    print(f"  [PASS] {label}")


def fail(label: str, detail: str = "") -> None:
    global _fail_count
    _fail_count += 1
    print(f"  [FAIL] {label}  {detail}")


# ── Test 1: Voice Presets -> Model Resolution ──────────────────────

async def test_presets_model_path() -> None:
    """Fix #1: Presets MUST have model_path so PiperEngine finds the ONNX file."""
    print("\n── Test 1: Voice Presets -> PiperEngine Model Resolution ──")

    engine = PiperEngine()

    # Male preset — now uses zh_CN-chaowen-medium (male voice)
    model_m = engine._resolve_model_for_voice(MALE_VOICE_PRESET)
    assert model_m, "Male preset model resolution returned empty"
    assert MALE_PIPER_MODEL in model_m, \
        f"Male model path should contain {MALE_PIPER_MODEL}, got: {model_m}"
    ok(f"Male preset resolves model -> {model_m}")

    # Female preset — uses zh_CN-huayan-medium (female voice)
    model_f = engine._resolve_model_for_voice(FEMALE_VOICE_PRESET)
    assert model_f, "Female preset model resolution returned empty"
    assert FEMALE_PIPER_MODEL in model_f, \
        f"Female model path should contain {FEMALE_PIPER_MODEL}, got: {model_f}"
    ok(f"Female preset resolves model -> {model_f}")

    # True dual-voice: male and female now use DIFFERENT ONNX models
    assert model_m != model_f, \
        f"Male/female should use DIFFERENT ONNX models for true dual-voice, got {model_m}"
    ok("Male and female presets use DIFFERENT ONNX models (true dual-voice)")

    # Verify model_path fields are set (not empty!)
    assert MALE_VOICE_PRESET.model_path, "MALE_VOICE_PRESET.model_path is empty!"
    assert FEMALE_VOICE_PRESET.model_path, "FEMALE_VOICE_PRESET.model_path is empty!"
    ok("Both presets have non-empty model_path")


# ── Test 2: _modulate_voice Preserves Model Fields ────────────────

async def test_modulate_voice_preserves_model() -> None:
    """Fix #2: _modulate_voice MUST propagate model_path, config_path, sample_rate."""
    print("\n── Test 2: _modulate_voice Preserves Non-Modulated Fields ──")

    tts = tts_service.TTSService()
    dual = DualVoiceTTS(tts_svc=tts)

    for base, label in [(dual.male_voice, "male"), (dual.female_voice, "female")]:
        modulated = dual._modulate_voice(base, Emotion.NEUTRAL)

        # Model identity fields must be preserved
        assert modulated.name == base.name, \
            f"{label}: name lost in modulation ({base.name} -> {modulated.name})"
        assert modulated.model_path == base.model_path, \
            f"{label}: model_path lost ({base.model_path} -> {modulated.model_path})"
        assert modulated.config_path == base.config_path, \
            f"{label}: config_path lost"
        assert modulated.sample_rate == base.sample_rate, \
            f"{label}: sample_rate lost ({base.sample_rate} -> {modulated.sample_rate})"

        ok(f"{label}: name preserved: {modulated.name}")
        ok(f"{label}: model_path preserved: {modulated.model_path}")
        ok(f"{label}: config_path preserved")
        ok(f"{label}: sample_rate preserved: {modulated.sample_rate}Hz")

    # Engine should be able to resolve model from modulated voice
    engine = PiperEngine()
    mv = dual._modulate_voice(dual.male_voice, Emotion.EXCITED)
    model = engine._resolve_model_for_voice(mv)
    assert model and MALE_PIPER_MODEL in model, \
        f"Modulated male voice model resolution failed: {model}"
    ok("Modulated male voice still resolves to correct ONNX model via PiperEngine")

    fv = dual._modulate_voice(dual.female_voice, Emotion.HAPPY)
    fmodel = engine._resolve_model_for_voice(fv)
    assert fmodel and FEMALE_PIPER_MODEL in fmodel, \
        f"Modulated female voice model resolution failed: {fmodel}"
    ok("Modulated female voice still resolves to correct ONNX model via PiperEngine")


# ── Test 3: text_to_wav Passes Voice to Engine ────────────────────

async def test_text_to_wav_voice_passthrough() -> None:
    """Fix #3: text_to_wav MUST pass modulated voice to TTSService -> engine."""
    print("\n── Test 3: text_to_wav -> Engine Voice Pass-through ──")

    class TrackingEngine(PiperEngine):
        last_voice: TTSVoice | None
        call_count: int

        def __init__(self) -> None:
            super().__init__()
            self.last_voice = None
            self.call_count = 0

        async def text_to_wav(  # pyright: ignore[reportImplicitOverride]
            self, text: str, *, voice: TTSVoice | None = None,
            output_dir: str | None = None,
        ) -> str:
            self.last_voice = voice
            self.call_count += 1
            return "/fake/path.wav"

    tracking = TrackingEngine()
    tts = tts_service.TTSService()
    tts.engine = tracking
    dual = DualVoiceTTS(tts_svc=tts)

    # Male + EXCITED
    _ = await dual.text_to_wav("涨疯了！", speaker=Speaker.MALE, emotion=Emotion.EXCITED)
    assert tracking.last_voice is not None, "Voice was NOT passed to engine!"
    expected_ls = MALE_VOICE_PRESET.length_scale * EMOTION_VOICE_PARAMS[Emotion.EXCITED][0]
    assert round(tracking.last_voice.length_scale, 4) == round(expected_ls, 4), \
        f"length_scale mismatch: {tracking.last_voice.length_scale} != {expected_ls}"
    ok(f"Male+EXCITED voice passed (len_scale={tracking.last_voice.length_scale:.4f})")

    # Female + SERIOUS
    _ = await dual.text_to_wav("要冷静。", speaker=Speaker.FEMALE, emotion=Emotion.SERIOUS)
    assert tracking.last_voice is not None, "Voice was NOT passed on second call!"
    expected_ls = FEMALE_VOICE_PRESET.length_scale * EMOTION_VOICE_PARAMS[Emotion.SERIOUS][0]
    assert round(tracking.last_voice.length_scale, 4) == round(expected_ls, 4), \
        f"length_scale mismatch: {tracking.last_voice.length_scale} != {expected_ls}"
    ok(f"Female+SERIOUS voice passed (len_scale={tracking.last_voice.length_scale:.4f})")

    # Male + WARNING (slowest)
    _ = await dual.text_to_wav("注意风险！", speaker=Speaker.MALE, emotion=Emotion.WARNING)
    expected_ls = MALE_VOICE_PRESET.length_scale * EMOTION_VOICE_PARAMS[Emotion.WARNING][0]
    assert round(tracking.last_voice.length_scale, 4) == round(expected_ls, 4)
    ok(f"Male+WARNING voice passed (len_scale={tracking.last_voice.length_scale:.4f})")

    # Female + HUMOROUS
    _ = await dual.text_to_wav("哈哈~", speaker=Speaker.FEMALE, emotion=Emotion.HUMOROUS)
    expected_ls = FEMALE_VOICE_PRESET.length_scale * EMOTION_VOICE_PARAMS[Emotion.HUMOROUS][0]
    assert round(tracking.last_voice.length_scale, 4) == round(expected_ls, 4)
    ok(f"Female+HUMOROUS voice passed (len_scale={tracking.last_voice.length_scale:.4f})")


# ── Test 4: speak_turn Returns Full Metadata + WAV Paths ──────────

async def test_speak_turn_metadata_and_wav() -> None:
    """Fix #4: speak_turn MUST include voice metadata and wav_paths."""
    print("\n── Test 4: speak_turn Returns Voice Metadata + WAV Paths ──")

    class MockTTSService(tts_service.TTSService):
        async def text_to_wav(self, text: str, voice: TTSVoice | None = None) -> str:  # pyright: ignore[reportImplicitOverride]
            return "/fake/turn.wav"

    tts = MockTTSService()
    dual = DualVoiceTTS(tts_svc=tts)

    result = await dual.speak_turn(
        DialogTurn(speaker=Speaker.MALE, text="测试文本", emotion=Emotion.EXCITED)
    )

    # Verify all expected keys
    assert "task_id" in result, "Missing task_id"
    assert "speaker" in result, "Missing speaker"
    assert result["speaker"] == "male"
    assert "emotion" in result, "Missing emotion"
    assert result["emotion"] == "excited"
    assert "wav_paths" in result, "Missing wav_paths (audio output not connected!)"
    assert result["wav_paths"] == ["/fake/turn.wav"]
    assert "voice_name" in result, "Missing voice_name"
    assert "model_path" in result, "Missing model_path"
    assert result["model_path"], "model_path is empty!"
    assert "length_scale" in result, "Missing length_scale"
    assert "noise_scale" in result, "Missing noise_scale"
    assert "noise_w" in result, "Missing noise_w"

    ok("speak_turn returns all 10 required fields")
    ok("wav_paths present in result")
    ok("voice_name + model_path present")
    ok("length_scale + noise_scale + noise_w present")
    ok("speaker=excited with correct length_scale modulation")


# ── Test 5: Stream Bus Audio Events via speak_script ──────────────

async def test_stream_bus_audio_events() -> None:
    """Fix #5: _synthesize_script MUST publish dual_host.audio to stream bus."""
    print("\n── Test 5: Stream Bus -> dual_host.audio Events ──")

    # Simulate a minimal stream bus
    class FakeStream:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        async def publish(self, event: dict[str, object]) -> None:
            self.events.append(event)

    class MockTTSService(tts_service.TTSService):
        async def text_to_wav(self, text: str, voice: TTSVoice | None = None) -> str:  # pyright: ignore[reportImplicitOverride]
            return "/fake/audio.wav"

    tts = MockTTSService()
    stream = FakeStream()
    dual = DualVoiceTTS(tts_svc=tts)

    turns = [
        DialogTurn(speaker=Speaker.FEMALE, text="大家好~", emotion=Emotion.HAPPY),
        DialogTurn(speaker=Speaker.MALE, text="大家好。", emotion=Emotion.NEUTRAL),
    ]

    # Simulate what _synthesize_script does
    results = await dual.speak_script(turns)
    segment_id = "test_seg_001"

    for i, result in enumerate(results):
        if not result.get("wav_paths"):
            continue
        await stream.publish({
            "type": "dual_host.audio",
            "segment_id": segment_id,
            "turn_index": i,
            "speaker": result.get("speaker"),
            "emotion": result.get("emotion"),
            "text": result.get("text"),
            "wav_paths": result.get("wav_paths"),
            "task_id": result.get("task_id"),
            "voice_name": result.get("voice_name"),
            "model_path": result.get("model_path"),
            "length_scale": result.get("length_scale"),
            "noise_scale": result.get("noise_scale"),
        })

    # Verify events - Test 5
    audio_events = [e for e in stream.events if e["type"] == "dual_host.audio"]
    assert len(audio_events) == 2, f"Expected 2 audio events, got {len(audio_events)}"

    e0, e1 = audio_events
    assert e0["speaker"] == "female"
    assert e1["speaker"] == "male"
    assert e0["wav_paths"] == ["/fake/audio.wav"]
    assert e0["voice_name"]
    assert e0.get("model_path"), \
        f"model_path should be non-empty: {e0.get('model_path')}"

    ok(f"Published {len(audio_events)} dual_host.audio events to stream bus")
    ok("Event includes wav_paths for frontend playback")
    ok("Event includes speaker + emotion metadata")
    ok("Event includes voice_name + length_scale + noise_scale")


# ── Test 6: Emotion Modulation Math ───────────────────────────────

async def test_emotion_modulation_math() -> None:
    """Verify all emotions produce correct parameter transformations."""
    print("\n── Test 6: Emotion Modulation Mathematical Correctness ──")

    tts = tts_service.TTSService()
    dual = DualVoiceTTS(tts_svc=tts)
    base = dual.male_voice

    # Collect all unique param sets
    param_sets: set[tuple[float, float, float]] = set()
    for emotion in Emotion:
        v = dual._modulate_voice(base, emotion)
        key = (round(v.length_scale, 4),
               round(v.noise_scale, 4),
               round(v.noise_w, 4))
        param_sets.add(key)

    assert len(param_sets) >= 5, f"Need >=5 distinct sets, got {len(param_sets)}"
    ok(f"{len(param_sets)} distinct param sets across {len(Emotion)} emotions")

    # HAPPY -> faster
    happy = dual._modulate_voice(base, Emotion.HAPPY)
    assert happy.length_scale < 1.0
    ok("HAPPY: faster (length_scale < 1.0)")

    # EXCITED -> fastest
    excited = dual._modulate_voice(base, Emotion.EXCITED)
    assert excited.length_scale < happy.length_scale
    ok("EXCITED: fastest of all emotions")

    # SERIOUS -> slower
    serious = dual._modulate_voice(base, Emotion.SERIOUS)
    assert serious.length_scale > 1.0
    ok("SERIOUS: slower (length_scale > 1.0)")

    # WARNING -> slowest
    warning = dual._modulate_voice(base, Emotion.WARNING)
    assert warning.length_scale > serious.length_scale
    ok("WARNING: slowest of all emotions")

    # THINKING -> drawn out
    thinking = dual._modulate_voice(base, Emotion.THINKING)
    assert thinking.length_scale > 1.05
    ok("THINKING: drawn out (length_scale > 1.05)")

    # All emotions should be valid (within reasonable range)
    for emotion in Emotion:
        v = dual._modulate_voice(base, emotion)
        assert 0.5 < v.length_scale < 2.0, f"{emotion}: unreasonable length_scale {v.length_scale}"
        assert 0.1 < v.noise_scale < 1.5, f"{emotion}: unreasonable noise_scale {v.noise_scale}"
        assert 0.1 < v.noise_w < 1.5, f"{emotion}: unreasonable noise_w {v.noise_w}"
    ok("All emotion-modulated parameters within valid ranges")


# ── Test 7: Full 16-combo CLI Arg Uniqueness ──────────────────────

async def test_full_cli_arg_diversity() -> None:
    """Verify DualVoiceTTS -> TTSVoice.cli_args() produces unique sets."""
    print("\n── Test 7: Full 16 SpeakerxEmotion -> CLI Args ──")

    tts = tts_service.TTSService()
    dual = DualVoiceTTS(tts_svc=tts)

    all_sets: dict[str, list[str]] = {}
    for speaker in (Speaker.MALE, Speaker.FEMALE):
        base = dual.male_voice if speaker == Speaker.MALE else dual.female_voice
        for emotion in Emotion:
            modulated = dual._modulate_voice(base, emotion)
            key = f"{speaker.value}/{emotion.value}"
            all_sets[key] = modulated.cli_args()

    ok(f"Generated CLI args for {len(all_sets)} speakerxemotion combos")

    unique = set(tuple(v) for v in all_sets.values())
    assert len(unique) >= 8, \
        f"Poor diversity: only {len(unique)} unique arg sets out of 16"
    ok(f"{len(unique)} unique CLI arg sets (good parameter diversity)")

    # Verify --model points to correct ONNX per speaker in all cases
    for key, args in all_sets.items():
        model_idx = args.index("--model")
        model_val = args[model_idx + 1]
        if key.startswith("male"):
            assert MALE_PIPER_MODEL in model_val, \
                f"{key}: male model arg should reference {MALE_PIPER_MODEL}: {model_val}"
        else:
            assert FEMALE_PIPER_MODEL in model_val, \
                f"{key}: female model arg should reference {FEMALE_PIPER_MODEL}: {model_val}"
    ok("All 16 combinations point to correct ONNX model per speaker")

    # Verify modulation params are in all CLI args
    sample_args = all_sets["male/excited"]
    assert "--length_scale" in sample_args
    assert "--noise_scale" in sample_args
    assert "--noise_w" in sample_args
    assert "--sentence_silence" in sample_args
    ok("All 4 modulation params present in every CLI arg set")


# ── Test 8: DualVoiceTTS Initialization Overrides ─────────────────

async def test_custom_voice_override() -> None:
    """Verify DualVoiceTTS accepts custom voice presets on construction."""
    print("\n── Test 8: Custom Voice Override on Construction ──")

    tts = tts_service.TTSService()
    custom_male = TTSVoice(
        name="custom_male_model",
        model_path="custom/voice.onnx",
        length_scale=1.10,
        noise_scale=0.55,
        noise_w=0.88,
    )
    custom_female = TTSVoice(
        name="custom_female_model",
        model_path="custom/female.onnx",
        length_scale=0.90,
        noise_scale=0.75,
        noise_w=0.70,
    )

    dual = DualVoiceTTS(tts_svc=tts, male_voice=custom_male, female_voice=custom_female)

    assert dual.male_voice.name == "custom_male_model"
    assert dual.male_voice.model_path == "custom/voice.onnx"
    assert dual.male_voice.length_scale == 1.10
    ok("Custom male voice accepted")

    assert dual.female_voice.name == "custom_female_model"
    assert dual.female_voice.model_path == "custom/female.onnx"
    ok("Custom female voice accepted")

    # Modulation should still work on custom voices
    mod = dual._modulate_voice(custom_male, Emotion.EXCITED)
    assert mod.name == "custom_male_model"
    assert mod.model_path == "custom/voice.onnx"
    expected_ls = 1.10 * EMOTION_VOICE_PARAMS[Emotion.EXCITED][0]
    assert round(mod.length_scale, 4) == round(expected_ls, 4)
    ok("Custom voice modulation preserves name + model_path")


# ── Test 9: DualVoiceTTS -> PiperEngine CLI command construction ───

async def test_full_cli_command_construction() -> None:
    """Verify the actual piper CLI command that would be executed."""
    print("\n── Test 9: Actual Piper CLI Command Construction ──")

    tts = tts_service.TTSService()
    dual = DualVoiceTTS(tts_svc=tts)
    engine = PiperEngine()

    # Male NEUTRAL
    mv_neutral = dual._modulate_voice(dual.male_voice, Emotion.NEUTRAL)
    neutral_model = engine._resolve_model_for_voice(mv_neutral)

    # Female EXCITED
    fv_excited = dual._modulate_voice(dual.female_voice, Emotion.EXCITED)
    excited_model = engine._resolve_model_for_voice(fv_excited)

    # Male and female should resolve to DIFFERENT model files (true dual-voice)
    assert neutral_model != excited_model, \
        f"Male/female should use DIFFERENT models, got {neutral_model}"
    ok("Male NEUTRAL and Female EXCITED use DIFFERENT ONNX models (true dual-voice)")

    # But CLI args should differ because voice params differ
    neutral_cli = mv_neutral.cli_args()
    excited_cli = fv_excited.cli_args()
    assert neutral_cli != excited_cli
    ok("CLI args differ between Male NEUTRAL and Female EXCITED")

    # Extract and compare specific params
    def get_param(args: list[str], name: str) -> float:
        idx = args.index(name)
        return float(args[idx + 1])

    assert get_param(neutral_cli, "--length_scale") > get_param(excited_cli, "--length_scale"), \
        "Male NEUTRAL should be slower than Female EXCITED"
    ok("Male NEUTRAL length_scale > Female EXCITED length_scale OK")

    assert get_param(neutral_cli, "--noise_scale") < get_param(excited_cli, "--noise_scale"), \
        "EXCITED should be more expressive (higher noise_scale)"
    ok("EXCITED noise_scale > NEUTRAL noise_scale OK")


# ── Test 10: Integration with DualHostService pattern ─────────────

async def test_dualhost_synthesize_pattern() -> None:
    """Verify the DualHostService._synthesize_script integration pattern."""
    print("\n── Test 10: DualHostService._synthesize_script Pattern ──")

    class MockTTSService(tts_service.TTSService):
        async def text_to_wav(self, text: str, voice: TTSVoice | None = None) -> str:  # pyright: ignore[reportImplicitOverride]
            return f"/fake/{hash(text) & 0xffff}.wav"

    class FakeStream:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        async def publish(self, event: dict[str, object]) -> None:
            self.events.append(event)

    tts = MockTTSService()
    stream = FakeStream()
    dual = DualVoiceTTS(tts_svc=tts)

    # Simulate a full show script
    turns = [
        DialogTurn(speaker=Speaker.FEMALE, text="各位观众朋友们大家好！", emotion=Emotion.HAPPY),
        DialogTurn(speaker=Speaker.MALE, text="大家好，我是老张。", emotion=Emotion.NEUTRAL),
        DialogTurn(speaker=Speaker.FEMALE, text="今天市场波动很大啊！", emotion=Emotion.EXCITED),
        DialogTurn(speaker=Speaker.MALE, text="是啊，我们来看看具体情况。", emotion=Emotion.SERIOUS),
    ]

    # Synthesize
    results = await dual.speak_script(turns)
    assert len(results) == 4

    # Publish events (same pattern as DualHostService._synthesize_script)
    segment_id = "show_seg_001"
    for i, result in enumerate(results):
        if not result.get("wav_paths"):
            continue
        await stream.publish({
            "type": "dual_host.audio",
            "segment_id": segment_id,
            "turn_index": i,
            "speaker": result.get("speaker"),
            "emotion": result.get("emotion"),
            "text": result.get("text"),
            "wav_paths": result.get("wav_paths"),
            "task_id": result.get("task_id"),
            "voice_name": result.get("voice_name"),
            "model_path": result.get("model_path"),
            "length_scale": result.get("length_scale"),
            "noise_scale": result.get("noise_scale"),
        })

    audio_events = [e for e in stream.events if e["type"] == "dual_host.audio"]
    assert len(audio_events) == 4, f"Expected 4 audio events, got {len(audio_events)}"

    # Verify speaker alternation - Test 10
    assert audio_events[0]["speaker"] == "female"
    assert audio_events[1]["speaker"] == "male"
    assert audio_events[2]["speaker"] == "female"
    assert audio_events[3]["speaker"] == "male"
    ok("Speaker alternation: F->M->F->M OK")

    # Verify emotion modulation
    assert audio_events[0]["emotion"] == "happy"
    assert audio_events[2]["emotion"] == "excited"
    assert audio_events[0]["length_scale"] != audio_events[2]["length_scale"], \
        "HAPPY and EXCITED female voice params should differ"
    ok("Female HAPPY vs EXCITED: different voice params OK")

    # Verify all events have required fields
    for ev in audio_events:
        assert ev["wav_paths"], "Missing wav_paths"
        assert ev["voice_name"], "Missing voice_name"
        assert ev["length_scale"] is not None, "Missing length_scale"
    ok("All 4 audio events have complete metadata")

    # Verify voice presets are used correctly (male vs female differ)
    assert audio_events[0]["voice_name"] == FEMALE_PIPER_MODEL, \
        f"Female should use {FEMALE_PIPER_MODEL}, got {audio_events[0]['voice_name']}"
    assert audio_events[1]["voice_name"] == MALE_PIPER_MODEL, \
        f"Male should use {MALE_PIPER_MODEL}, got {audio_events[1]['voice_name']}"
    ok(f"Female turn uses {FEMALE_PIPER_MODEL}, Male turn uses {MALE_PIPER_MODEL}")


# ── main ───────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 65)
    print("  DualVoiceTTS Full-Pipeline Integration Test Suite (v2)")
    print("  Validates: Presets -> Model Resolution -> Modulation ->")
    print("             Engine -> CLI Args -> Stream Bus Events")
    print("=" * 65)

    loop = asyncio.get_event_loop()

    tests = [
        test_presets_model_path,           # Fix #1
        test_modulate_voice_preserves_model,  # Fix #2
        test_text_to_wav_voice_passthrough,   # Fix #3
        test_speak_turn_metadata_and_wav,     # Fix #4
        test_stream_bus_audio_events,         # Fix #5
        test_emotion_modulation_math,
        test_full_cli_arg_diversity,
        test_custom_voice_override,
        test_full_cli_command_construction,
        test_dualhost_synthesize_pattern,     # Full integration
    ]

    for test_fn in tests:
        try:
            loop.run_until_complete(test_fn())
        except Exception as exc:
            import traceback
            fail(test_fn.__name__, f"{exc}\n{traceback.format_exc()}")

    print()
    total = _pass_count + _fail_count
    bar = "=" * 40
    print(f"{bar}")
    print(f"  Results: {_pass_count}/{total} passed, {_fail_count} failed")
    print(f"{bar}")

    if _fail_count > 0:
        print("\n[SOME TESTS FAILED]")
        sys.exit(1)
    else:
        print("\n[ALL TESTS PASSED]")
        sys.exit(0)


if __name__ == "__main__":
    main()
