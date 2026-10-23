"""Tests for the MP3 transcode service + LRU cache.

These exercise the real ``ffmpeg`` binary (skipped when unavailable) using
tiny synthesized WAV sources, plus the cache/LRU bookkeeping which is pure
Python and always runs.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import wave
from pathlib import Path

import pytest

from desktop_music.services.remote.transcode import (
    TranscodeCache,
    TranscodeError,
    TrackRef,
    transcode_to_mp3,
)

_HAS_FFMPEG = shutil.which("ffmpeg") is not None
_ffmpeg_required = pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg not installed")


def _make_wav(path: Path, seconds: float = 1.0, rate: int = 8000) -> Path:
    """Write a tiny silent mono WAV so ffmpeg has something to transcode."""
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<" + "h" * frames, *([0] * frames)))
    return path


# -- cache key / naming (no ffmpeg needed) --------------------------------


def test_cache_key_changes_with_segment(tmp_path):
    src = _make_wav(tmp_path / "a.wav")
    whole = TrackRef(str(src)).cache_key()
    seg = TrackRef(str(src), start_ms=1000, end_ms=2000).cache_key()
    assert whole != seg


def test_cache_key_changes_when_file_changes(tmp_path):
    src = tmp_path / "a.wav"
    _make_wav(src, seconds=1.0)
    key1 = TrackRef(str(src)).cache_key()
    _make_wav(src, seconds=2.0)  # different size/mtime
    key2 = TrackRef(str(src)).cache_key()
    assert key1 != key2


def test_missing_source_raises(tmp_path):
    cache = TranscodeCache(tmp_path / "cache")
    with pytest.raises(TranscodeError):
        cache.get_or_create(TrackRef(str(tmp_path / "nope.wav")))


# -- real transcoding (ffmpeg) --------------------------------------------


@_ffmpeg_required
def test_transcode_produces_mp3(tmp_path):
    src = _make_wav(tmp_path / "a.wav", seconds=1.0)
    cache = TranscodeCache(tmp_path / "cache")
    out = cache.get_or_create(TrackRef(str(src)))
    assert out.exists() and out.stat().st_size > 0
    assert out.suffix == ".mp3"
    # ffprobe-free sniff: an MP3 frame header or an ID3 tag at the start.
    head = out.read_bytes()[:3]
    assert head[:2] == b"\xff\xfb" or head[:2] == b"\xff\xf3" or head == b"ID3"


@_ffmpeg_required
def test_transcode_cache_hit_reuses_file(tmp_path):
    src = _make_wav(tmp_path / "a.wav")
    cache = TranscodeCache(tmp_path / "cache")
    ref = TrackRef(str(src))
    first = cache.get_or_create(ref)
    mtime_before = first.stat().st_mtime_ns
    second = cache.get_or_create(ref)
    assert first == second
    # Hit path should touch (>=) but never rewrite a different file.
    assert second.stat().st_mtime_ns >= mtime_before


@_ffmpeg_required
def test_lru_evicts_beyond_max(tmp_path):
    cache = TranscodeCache(tmp_path / "cache", max_entries=5)
    outputs = []
    for i in range(6):
        src = _make_wav(tmp_path / f"t{i}.wav", seconds=0.5)
        outputs.append(cache.get_or_create(TrackRef(str(src))))
    remaining = list((tmp_path / "cache").glob("*.mp3"))
    assert len(remaining) == 5
    # The very first file should have been evicted as least-recently-used.
    assert not outputs[0].exists()
    assert outputs[-1].exists()


@_ffmpeg_required
def test_transcode_segment_shorter_than_whole(tmp_path):
    src = _make_wav(tmp_path / "a.wav", seconds=3.0)
    cache = TranscodeCache(tmp_path / "cache")
    whole = cache.get_or_create(TrackRef(str(src)))
    seg = cache.get_or_create(TrackRef(str(src), start_ms=0, end_ms=1000))
    assert whole != seg
    # A 1s segment should be meaningfully smaller than the 3s whole file.
    assert seg.stat().st_size < whole.stat().st_size


@_ffmpeg_required
def test_module_level_helper(tmp_path):
    src = _make_wav(tmp_path / "a.wav")
    cache = TranscodeCache(tmp_path / "cache")
    out = transcode_to_mp3(str(src), cache=cache)
    assert out.exists() and out.stat().st_size > 0
