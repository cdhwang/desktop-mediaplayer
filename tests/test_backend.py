"""Tests for the VLC backend wrapper (Task 2).

A short synthetic WAV file is generated so the tests need no external
assets. Playback assertions are lenient about timing because libVLC is
asynchronous and audio output may be unavailable in headless CI.
"""

from __future__ import annotations

import math
import struct
import time
import wave
from pathlib import Path

import pytest

from desktop_music.services.backend import PlaybackState, VLCBackend


@pytest.fixture(scope="module")
def wav_file(tmp_path_factory) -> str:
    """Create a 1-second 440Hz mono WAV file and return its path."""
    path = tmp_path_factory.mktemp("audio") / "tone.wav"
    _write_sine_wav(path, freq=440.0, seconds=1.0, rate=44100)
    return str(path)


def _write_sine_wav(path: Path, freq: float, seconds: float, rate: int) -> None:
    n = int(rate * seconds)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)  # 16-bit
        w.setframerate(rate)
        frames = bytearray()
        for i in range(n):
            sample = int(32767 * 0.3 * math.sin(2 * math.pi * freq * i / rate))
            frames += struct.pack("<h", sample)
        w.writeframes(bytes(frames))


def test_load_sets_current_path(wav_file) -> None:
    backend = VLCBackend()
    backend.load(wav_file)
    assert backend.current_path == wav_file
    backend.release()


def test_volume_clamping() -> None:
    backend = VLCBackend()
    backend.set_volume(150)
    assert backend.get_volume() <= 100
    backend.set_volume(-10)
    assert backend.get_volume() >= 0
    backend.release()


def test_mute_toggle() -> None:
    backend = VLCBackend()
    backend.set_muted(True)
    assert backend.is_muted() is True
    backend.set_muted(False)
    assert backend.is_muted() is False
    backend.release()


def test_rate() -> None:
    backend = VLCBackend()
    backend.set_rate(1.5)
    assert abs(backend.get_rate() - 1.5) < 1e-6
    backend.release()


def test_state_transitions(wav_file) -> None:
    backend = VLCBackend()
    assert backend.get_state() in (PlaybackState.IDLE, PlaybackState.STOPPED)
    backend.load(wav_file)
    backend.play()
    # libVLC opens asynchronously; poll briefly for a "live" state.
    live = {PlaybackState.OPENING, PlaybackState.BUFFERING, PlaybackState.PLAYING}
    reached = False
    for _ in range(50):
        if backend.get_state() in live:
            reached = True
            break
        time.sleep(0.05)
    assert reached, f"unexpected state {backend.get_state()}"
    backend.stop()
    backend.release()
