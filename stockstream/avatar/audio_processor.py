"""Audio processor — WAV → mel spectrogram for Wav2Lip input.

Wav2Lip expects:
- 16 kHz mono audio
- 80-bin mel spectrogram
- hop_length = 200 (12.5 ms window step)
- win_length = 800 (50 ms window)
"""

from __future__ import annotations

import logging
import wave
from pathlib import Path
from typing import Optional

import numpy as np

from stockstream.avatar.models import MelSpectrogram

logger = logging.getLogger(__name__)

_LIBROSA_AVAILABLE = False
_SOUNDFILE_AVAILABLE = False


def _ensure_librosa() -> bool:
    global _LIBROSA_AVAILABLE
    if _LIBROSA_AVAILABLE:
        return True
    try:
        import librosa  # noqa: F401
        _LIBROSA_AVAILABLE = True
        return True
    except ImportError:
        return False


def _ensure_soundfile() -> bool:
    global _SOUNDFILE_AVAILABLE
    if _SOUNDFILE_AVAILABLE:
        return True
    try:
        import soundfile  # noqa: F401
        _SOUNDFILE_AVAILABLE = True
        return True
    except ImportError:
        return False


class AudioProcessor:
    """Extract mel spectrograms from WAV files for Wav2Lip.

    Wav2Lip standard:
    - Target SR: 16000 Hz
    - Mel bins:  80
    - FFT size:  800 (win_length)
    - Hop:       200
    - Min freq:  55 Hz
    - Max freq:  7600 Hz
    """

    TARGET_SR = 16000
    N_MELS = 80
    HOP_LENGTH = 200
    WIN_LENGTH = 800
    FMIN = 55.0
    FMAX = 7600.0

    def __init__(self) -> None:
        self._mel_basis: np.ndarray | None = None

    # ── main API ───────────────────────────────────────────────────

    def process(self, wav_path: str | Path) -> Optional[MelSpectrogram]:
        """Load a WAV file and extract mel spectrogram.

        Args:
            wav_path: Path to a 16-bit PCM mono/stereo WAV file.

        Returns:
            MelSpectrogram or None on failure.
        """
        wav_path = Path(wav_path)

        # Load audio samples
        samples, sr = self._load_wav(wav_path)
        if samples is None or len(samples) == 0:
            logger.error("Failed to load audio from %s", wav_path)
            return None

        # Resample to 16 kHz if needed
        if sr != self.TARGET_SR:
            samples = self._resample(samples, sr, self.TARGET_SR)

        # Mono
        if samples.ndim > 1:
            samples = samples.mean(axis=1)

        duration = len(samples) / self.TARGET_SR

        # Compute mel spectrogram
        mel = self._compute_mel(samples)

        return MelSpectrogram(
            mel=mel.astype(np.float32),
            sample_rate=self.TARGET_SR,
            hop_length=self.HOP_LENGTH,
            win_length=self.WIN_LENGTH,
            n_mels=self.N_MELS,
            duration_s=duration,
        )

    # ── internal ───────────────────────────────────────────────────

    def _load_wav(self, path: Path) -> tuple[Optional[np.ndarray], int]:
        """Load raw audio samples from WAV file. Returns (samples, sample_rate)."""
        # Try soundfile first (supports more formats)
        if _ensure_soundfile():
            import soundfile as sf
            samples, sr = sf.read(str(path))
            return samples, sr

        # Fallback: standard library wave module (16-bit PCM only)
        try:
            with wave.open(str(path), "rb") as wf:
                sr = wf.getframerate()
                n_frames = wf.getnframes()
                n_channels = wf.getnchannels()
                raw = wf.readframes(n_frames)
                dtype = np.int16
                samples = np.frombuffer(raw, dtype=dtype).astype(np.float32) / 32768.0
                if n_channels > 1:
                    samples = samples.reshape(-1, n_channels)
                return samples, sr
        except Exception as exc:
            logger.error("wave loader error for %s: %s", path, exc)
            return None, 0

    def _resample(
        self, samples: np.ndarray, orig_sr: int, target_sr: int,
    ) -> np.ndarray:
        """Resample audio to target sample rate."""
        if _ensure_librosa():
            import librosa
            return librosa.resample(samples, orig_sr=orig_sr, target_sr=target_sr)

        # Simple linear interpolation fallback
        ratio = target_sr / orig_sr
        n_out = int(len(samples) * ratio)
        indices = np.arange(n_out) / ratio
        indices = np.clip(indices, 0, len(samples) - 1)
        lo = np.floor(indices).astype(int)
        hi = np.minimum(lo + 1, len(samples) - 1)
        frac = indices - lo
        return samples[lo] * (1 - frac) + samples[hi] * frac

    def _compute_mel(self, samples: np.ndarray) -> np.ndarray:
        """Compute 80-bin mel spectrogram from 16kHz mono audio."""
        if _ensure_librosa():
            import librosa
            mel = librosa.feature.melspectrogram(
                y=samples,
                sr=self.TARGET_SR,
                n_fft=self.WIN_LENGTH,
                hop_length=self.HOP_LENGTH,
                win_length=self.WIN_LENGTH,
                n_mels=self.N_MELS,
                fmin=self.FMIN,
                fmax=self.FMAX,
                power=1.0,
            )
            # log scale
            return np.log(np.clip(mel, a_min=1e-5, a_max=None)).T  # (T, 80)

        # Pure numpy STFT fallback (simplified)
        return self._numpy_mel(samples)

    def _numpy_mel(self, samples: np.ndarray) -> np.ndarray:
        """Compute log-mel spectrogram using only numpy (no librosa)."""
        n_fft = self.WIN_LENGTH
        hop = self.HOP_LENGTH

        # Pad
        samples = np.pad(samples, n_fft // 2, mode="reflect")

        # Compute number of frames
        n_frames = 1 + (len(samples) - n_fft) // hop
        frames = np.lib.stride_tricks.sliding_window_view(
            samples[:n_fft + (n_frames - 1) * hop], n_fft
        )[::hop]

        # Hann window
        window = np.hanning(n_fft)
        frames = frames * window

        # FFT → power spectrogram
        spec = np.abs(np.fft.rfft(frames, n=n_fft, axis=1))  # (T, n_fft//2+1)
        spec = spec ** 1.0  # power = 1

        # Mel filterbank
        mel_basis = self._build_mel_basis(n_fft)
        mel = np.dot(spec, mel_basis.T)

        return np.log(np.clip(mel, a_min=1e-5, a_max=None))

    def _build_mel_basis(self, n_fft: int) -> np.ndarray:
        """Build mel filterbank matrix (n_mels, n_fft//2+1)."""
        if self._mel_basis is not None:
            return self._mel_basis

        n_freqs = n_fft // 2 + 1
        mel_min = self._hz_to_mel(self.FMIN)
        mel_max = self._hz_to_mel(self.FMAX)
        mel_points = np.linspace(mel_min, mel_max, self.N_MELS + 2)
        hz_points = self._mel_to_hz(mel_points)
        bin_indices = np.floor((n_fft + 1) * hz_points / self.TARGET_SR).astype(int)
        bin_indices = np.clip(bin_indices, 0, n_freqs - 1)

        filters = np.zeros((self.N_MELS, n_freqs), dtype=np.float32)
        for m in range(self.N_MELS):
            start, center, end = bin_indices[m], bin_indices[m + 1], bin_indices[m + 2]
            for k in range(start, center):
                filters[m, k] = (k - start) / max(1, center - start)
            for k in range(center, end + 1):
                if end > center:
                    filters[m, k] = (end - k) / (end - center)

        self._mel_basis = filters
        return filters

    @staticmethod
    def _hz_to_mel(hz: float) -> float:
        return 2595.0 * np.log10(1.0 + hz / 700.0)

    @staticmethod
    def _mel_to_hz(mel: float | np.ndarray) -> float | np.ndarray:
        return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)
