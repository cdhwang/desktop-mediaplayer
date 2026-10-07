"""Tests for ``.cue`` sheet handling.

A cue sheet given directly expands into the media files it references (the
cue file itself is never added); cue files found while scanning a directory
are excluded.
"""

from __future__ import annotations

import os

from desktop_music.core.playlist import PlaylistModel
from desktop_music.services.cue import is_cue, parse_cue_files
from desktop_music.ui.dnd import _is_droppable


def _write(path, data=b"\x00") -> str:
    with open(path, "wb") as fh:
        fh.write(data)
    return str(path)


def _make_album(tmp_path):
    """Create two referenced media files, one unrelated file, and a cue."""
    flac = _write(tmp_path / "Album.flac")
    wav = _write(tmp_path / "Bonus.wav")
    _write(tmp_path / "unrelated.mp3")
    cue = tmp_path / "Album.cue"
    cue.write_text(
        'TITLE "An Album"\n'
        'FILE "Album.flac" WAVE\n'
        "  TRACK 01 AUDIO\n"
        "    INDEX 01 00:00:00\n"
        "FILE Bonus.wav WAVE\n"
        "  TRACK 02 AUDIO\n"
        'FILE "Missing.flac" WAVE\n'   # referenced but absent -> skipped
        'FILE "notes.txt" WAVE\n'      # not a media file -> skipped
    )
    return flac, wav, str(cue)


# -- parser ----------------------------------------------------------------


def test_is_cue() -> None:
    assert is_cue("/x/Album.cue")
    assert is_cue("/x/ALBUM.CUE")
    assert not is_cue("/x/Album.flac")


def test_parse_cue_resolves_existing_media(tmp_path) -> None:
    flac, wav, cue = _make_album(tmp_path)
    refs = parse_cue_files(cue)
    assert refs == [os.path.normpath(flac), os.path.normpath(wav)]


def test_parse_cue_missing_file_returns_empty(tmp_path) -> None:
    assert parse_cue_files(str(tmp_path / "nope.cue")) == []


def test_parse_cue_accepts_ape(tmp_path) -> None:
    ape = _write(tmp_path / "Album.ape")
    cue = tmp_path / "Album.cue"
    cue.write_text('FILE "Album.ape" WAVE\n  TRACK 01 AUDIO\n')
    assert parse_cue_files(str(cue)) == [os.path.normpath(ape)]


def test_parse_cue_stem_fallback_on_extension_mismatch(tmp_path) -> None:
    # The cue references an .ape but only a same-stem .flac exists on disk.
    flac = _write(tmp_path / "Album.flac")
    cue = tmp_path / "Album.cue"
    cue.write_text('FILE "Album.ape" WAVE\n  TRACK 01 AUDIO\n')
    assert parse_cue_files(str(cue)) == [os.path.normpath(flac)]


# -- playlist integration --------------------------------------------------


def test_adding_cue_expands_and_excludes_cue_itself(tmp_path) -> None:
    flac, wav, cue = _make_album(tmp_path)
    m = PlaylistModel()
    added = m.add_paths([cue])
    paths = [t.path for t in m.tracks]
    assert added == 2
    assert cue not in paths
    assert os.path.normpath(flac) in paths
    assert os.path.normpath(wav) in paths


def test_directory_scan_excludes_cue(tmp_path) -> None:
    _make_album(tmp_path)
    m = PlaylistModel()
    m.add_paths([str(tmp_path)])
    paths = [t.path for t in m.tracks]
    assert not any(p.lower().endswith(".cue") for p in paths)
    # real media (including cue-referenced ones) still collected
    assert any(p.endswith("Album.flac") for p in paths)
    assert any(p.endswith("unrelated.mp3") for p in paths)


# -- drag & drop acceptance ------------------------------------------------


def test_dnd_accepts_cue_and_media_rejects_other(tmp_path) -> None:
    flac, _wav, cue = _make_album(tmp_path)
    assert _is_droppable(cue)
    assert _is_droppable(flac)
    assert _is_droppable(str(tmp_path))  # directory
    assert not _is_droppable(str(tmp_path / "notes.txt"))
