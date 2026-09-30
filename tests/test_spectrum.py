"""Tests for spectrum analysis and widget (Task 10)."""

from __future__ import annotations

import math
import struct
import subprocess
import wave
from pathlib import Path

import numpy as np

from desktop_music.services.spectrum import (
    NUM_BANDS,
    SpectrumData,
    analyze_file,
    compute_band_frames,
    frame_index_for_ms,
)
from desktop_music.ui.spectrum_widget import SpectrumWidget


# -- pure numpy analysis ---------------------------------------------------


def test_compute_band_frames_shape() -> None:
    # 1 second of a 440Hz sine at 22050 Hz
    rate = 22050
    t = np.arange(rate) / rate
    samples = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    frames = compute_band_frames(samples, sample_rate=rate)
    assert frames.ndim == 2
    assert frames.shape[1] == NUM_BANDS
    assert frames.shape[0] > 1
    # normalized to 0..1
    assert frames.max() <= 1.0 + 1e-6
    assert frames.min() >= 0.0


def test_compute_band_frames_tone_has_energy() -> None:
    rate = 22050
    t = np.arange(rate) / rate
    samples = np.sin(2 * np.pi * 1000 * t).astype(np.float32)
    frames = compute_band_frames(samples, sample_rate=rate)
    # some band should carry meaningful energy
    assert frames.max() > 0.1


def test_compute_band_frames_silence() -> None:
    samples = np.zeros(22050, dtype=np.float32)
    frames = compute_band_frames(samples)
    assert frames.shape[1] == NUM_BANDS
    assert float(frames.max()) == 0.0


def test_frame_index_for_ms_clamps() -> None:
    assert frame_index_for_ms(0, hop_ms=20.0, num_frames=10) == 0
    assert frame_index_for_ms(40, hop_ms=20.0, num_frames=10) == 2
    assert frame_index_for_ms(10_000, hop_ms=20.0, num_frames=10) == 9
    assert frame_index_for_ms(100, hop_ms=0.0, num_frames=10) == 0


def test_spectrum_data_frame_at_ms() -> None:
    frames = np.random.rand(5, NUM_BANDS).astype(np.float32)
    data = SpectrumData(frames=frames, hop_ms=20.0)
    assert data.num_frames == 5
    np.testing.assert_array_equal(data.frame_at_ms(0), frames[0])
    np.testing.assert_array_equal(data.frame_at_ms(40), frames[2])
    np.testing.assert_array_equal(data.frame_at_ms(999_999), frames[4])


def test_empty_spectrum_data() -> None:
    data = SpectrumData(frames=np.zeros((0, NUM_BANDS), dtype=np.float32), hop_ms=0.0)
    assert data.num_frames == 0
    assert data.frame_at_ms(100).shape == (NUM_BANDS,)


# -- decode + analyze (uses ffmpeg) ----------------------------------------


def test_analyze_file_flac(tmp_path) -> None:
    src = tmp_path / "t.wav"
    rate = 22050
    with wave.open(str(src), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(
            b"".join(
                struct.pack("<h", int(20000 * math.sin(2 * math.pi * 440 * i / rate)))
                for i in range(rate)  # 1 second
            )
        )
    flac = tmp_path / "song.flac"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "quiet", "-i", str(src), str(flac)],
        check=True,
    )
    data = analyze_file(str(flac))
    assert data.num_frames > 1
    assert data.hop_ms > 0


# -- widget ----------------------------------------------------------------


def test_spectrum_widget_basic(qtbot) -> None:
    w = SpectrumWidget()
    qtbot.addWidget(w)
    assert w.has_data is False
    # feeding data directly drives the animation tick without ffmpeg
    w._data = SpectrumData(
        frames=np.ones((3, NUM_BANDS), dtype=np.float32), hop_ms=20.0
    )
    w.set_position(20)
    w._tick()  # should not raise; updates internal levels
    assert w.has_data is True
