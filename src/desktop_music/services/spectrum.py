"""Offline spectrum analysis (hybrid visualization).

libVLC's audio callback mutes normal output, so instead of tapping the
live stream we pre-analyze the file: decode it to mono PCM (via ffmpeg),
run a short-time FFT, and reduce each frame to a handful of logarithmic
frequency-band magnitudes. The UI then renders the frame matching the
current playback position, giving a real-time feel while libVLC handles
audio output normally.

The pure numpy parts (``compute_band_frames``, ``frame_index_for_ms``) are
unit-tested directly; ffmpeg decoding is isolated in ``decode_pcm_mono``.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

import numpy as np

# analysis parameters
SAMPLE_RATE = 22_050
FFT_SIZE = 1024
HOP_SIZE = 512  # -> ~23ms frames at 22.05kHz
NUM_BANDS = 24


@dataclass
class SpectrumData:
    """Pre-computed per-frame band magnitudes for one media file."""

    frames: np.ndarray  # shape (n_frames, NUM_BANDS), values in 0..1
    hop_ms: float       # milliseconds advanced per frame

    @property
    def num_frames(self) -> int:
        return int(self.frames.shape[0])

    def frame_at_ms(self, ms: int) -> np.ndarray:
        """Return the band vector for playback position *ms* (clamped)."""
        if self.num_frames == 0:
            return np.zeros(NUM_BANDS, dtype=np.float32)
        idx = frame_index_for_ms(ms, self.hop_ms, self.num_frames)
        return self.frames[idx]


def frame_index_for_ms(ms: int, hop_ms: float, num_frames: int) -> int:
    """Map a playback position in ms to a frame index (clamped)."""
    if num_frames <= 0 or hop_ms <= 0:
        return 0
    idx = int(ms / hop_ms)
    return max(0, min(idx, num_frames - 1))


def compute_band_frames(
    samples: np.ndarray,
    sample_rate: int = SAMPLE_RATE,
    fft_size: int = FFT_SIZE,
    hop_size: int = HOP_SIZE,
    num_bands: int = NUM_BANDS,
) -> np.ndarray:
    """Compute per-frame log-band magnitudes from mono PCM *samples*.

    Returns an array of shape (n_frames, num_bands) normalized to 0..1.
    """
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    if samples.size < fft_size:
        samples = np.pad(samples, (0, fft_size - samples.size))

    window = np.hanning(fft_size).astype(np.float32)
    n_frames = 1 + (samples.size - fft_size) // hop_size
    if n_frames < 1:
        n_frames = 1

    # logarithmically spaced band edges across the FFT bins
    n_bins = fft_size // 2 + 1
    edges = np.logspace(0, np.log10(n_bins), num_bands + 1).astype(int)
    edges = np.clip(edges, 0, n_bins)

    frames = np.zeros((n_frames, num_bands), dtype=np.float32)
    for f in range(n_frames):
        start = f * hop_size
        chunk = samples[start : start + fft_size]
        if chunk.size < fft_size:
            chunk = np.pad(chunk, (0, fft_size - chunk.size))
        spectrum = np.abs(np.fft.rfft(chunk * window))
        for b in range(num_bands):
            lo, hi = edges[b], max(edges[b] + 1, edges[b + 1])
            frames[f, b] = spectrum[lo:hi].mean() if hi > lo else 0.0

    # log-scale compress and normalize to 0..1
    frames = np.log1p(frames)
    peak = frames.max()
    if peak > 0:
        frames /= peak
    return frames


def decode_pcm_mono(path: str, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Decode *path* to mono float32 PCM using ffmpeg. Returns [] on failure."""
    cmd = [
        "ffmpeg",
        "-v", "quiet",
        "-i", path,
        "-f", "f32le",
        "-ac", "1",
        "-ar", str(sample_rate),
        "-",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return np.zeros(0, dtype=np.float32)
    return np.frombuffer(result.stdout, dtype=np.float32)


def analyze_file(path: str) -> SpectrumData:
    """Decode and analyze *path* into :class:`SpectrumData`."""
    samples = decode_pcm_mono(path)
    if samples.size == 0:
        return SpectrumData(frames=np.zeros((0, NUM_BANDS), dtype=np.float32), hop_ms=0.0)
    frames = compute_band_frames(samples)
    hop_ms = 1000.0 * HOP_SIZE / SAMPLE_RATE
    return SpectrumData(frames=frames, hop_ms=hop_ms)
