"""Tests for lyrics extraction and view (Task 9)."""

from __future__ import annotations

import math
import struct
import subprocess
import wave
from pathlib import Path

import pytest

from desktop_music.services.lyrics import read_lyrics
from desktop_music.ui.central_display import PAGE_LYRICS, CentralDisplay
from desktop_music.ui.lyrics_view import LyricsView


def _write_wav(path: Path, seconds: float = 0.3, rate: int = 8000) -> None:
    n = int(rate * seconds)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(
            b"".join(struct.pack("<h", int(10000 * math.sin(i / 8))) for i in range(n))
        )


# -- embedded lyrics -------------------------------------------------------


def test_embedded_uslt_id3(tmp_path) -> None:
    path = tmp_path / "song.wav"
    _write_wav(path)
    from mutagen.id3 import USLT
    from mutagen.wave import WAVE

    audio = WAVE(str(path))
    if audio.tags is None:
        audio.add_tags()
    audio.tags.add(USLT(encoding=3, lang="eng", desc="", text="Embedded line 1\nline 2"))
    audio.save()

    assert read_lyrics(str(path)) == "Embedded line 1\nline 2"


def test_embedded_vorbis_flac(tmp_path) -> None:
    src = tmp_path / "t.wav"
    _write_wav(src)
    flac = tmp_path / "song.flac"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "quiet", "-i", str(src), str(flac)],
        check=True,
    )
    from mutagen.flac import FLAC

    audio = FLAC(str(flac))
    audio["lyrics"] = "Flac lyric line"
    audio.save()

    assert read_lyrics(str(flac)) == "Flac lyric line"


# -- sidecar files ---------------------------------------------------------


def test_sidecar_txt(tmp_path) -> None:
    media = tmp_path / "song.mp3"
    media.write_bytes(b"")
    (tmp_path / "song.txt").write_text("Sidecar lyrics here", encoding="utf-8")
    assert read_lyrics(str(media)) == "Sidecar lyrics here"


def test_sidecar_lrc_strips_timestamps(tmp_path) -> None:
    media = tmp_path / "song.mp3"
    media.write_bytes(b"")
    lrc = "[ti:Song]\n[00:12.00]First line\n[00:15.30]Second line\n"
    (tmp_path / "song.lrc").write_text(lrc, encoding="utf-8")
    result = read_lyrics(str(media))
    assert "First line" in result
    assert "Second line" in result
    assert "[00:12" not in result
    assert "[ti:" not in result


def test_lrc_preferred_over_txt(tmp_path) -> None:
    media = tmp_path / "song.mp3"
    media.write_bytes(b"")
    (tmp_path / "song.lrc").write_text("[00:01.00]From LRC", encoding="utf-8")
    (tmp_path / "song.txt").write_text("From TXT", encoding="utf-8")
    assert read_lyrics(str(media)) == "From LRC"


def test_no_lyrics(tmp_path) -> None:
    media = tmp_path / "bare.wav"
    _write_wav(media)
    assert read_lyrics(str(media)) == ""


# -- view / central display ------------------------------------------------


def test_lyrics_view_set_and_clear(qtbot) -> None:
    view = LyricsView()
    qtbot.addWidget(view)
    assert view.has_lyrics is False
    view.set_lyrics("Hello world")
    assert view.has_lyrics is True
    view.clear()
    assert view.has_lyrics is False


def test_central_display_has_lyrics_page(qtbot) -> None:
    display = CentralDisplay()
    qtbot.addWidget(display)
    assert display.has_page(PAGE_LYRICS)
    display.set_lyrics("abc")
    display.show_page(PAGE_LYRICS)
    assert display.current_page == PAGE_LYRICS
