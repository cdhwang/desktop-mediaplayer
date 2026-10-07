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


# -- per-track expansion (one song per cue TRACK) --------------------------


def test_cue_single_file_splits_into_tracks(tmp_path) -> None:
    from desktop_music.services.cue import parse_cue_tracks, _mmssff_to_ms

    ape = _write(tmp_path / "Album.ape")
    cue = tmp_path / "Album.cue"
    cue.write_text(
        'PERFORMER "Band"\n'
        'TITLE "The Album"\n'
        'FILE "Album.ape" WAVE\n'
        '  TRACK 01 AUDIO\n'
        '    TITLE "Opener"\n'
        '    INDEX 01 00:00:00\n'
        '  TRACK 02 AUDIO\n'
        '    TITLE "Second"\n'
        '    INDEX 01 02:30:00\n'
        '  TRACK 03 AUDIO\n'
        '    TITLE "Closer"\n'
        '    INDEX 01 05:00:00\n'
    )
    tracks = parse_cue_tracks(str(cue))
    assert [t.title for t in tracks] == ["Opener", "Second", "Closer"]
    assert all(t.path == os.path.normpath(ape) for t in tracks)
    assert all(t.artist == "Band" for t in tracks)
    assert tracks[0].start_ms == 0
    assert tracks[1].start_ms == _mmssff_to_ms(2, 30, 0)
    assert tracks[2].start_ms == _mmssff_to_ms(5, 0, 0)
    # end offsets chain to the next track's start; last is 0 (to EOF)
    assert tracks[0].end_ms == tracks[1].start_ms
    assert tracks[1].end_ms == tracks[2].start_ms
    assert tracks[2].end_ms == 0


def test_adding_single_file_cue_adds_one_item_per_track(tmp_path) -> None:
    _write(tmp_path / "Album.ape")
    cue = tmp_path / "Album.cue"
    cue.write_text(
        'FILE "Album.ape" WAVE\n'
        '  TRACK 01 AUDIO\n    TITLE "A"\n    INDEX 01 00:00:00\n'
        '  TRACK 02 AUDIO\n    TITLE "B"\n    INDEX 01 03:00:00\n'
    )
    m = PlaylistModel()
    added = m.add_paths([str(cue)])
    assert added == 2
    assert [t.title for t in m.tracks] == ["A", "B"]
    assert m.tracks[0].is_cue_track is True  # has an end bound
    assert m.tracks[0].end_ms > 0
    assert not any(t.path.endswith(".cue") for t in m.tracks)


def test_mmssff_conversion() -> None:
    from desktop_music.services.cue import _mmssff_to_ms

    assert _mmssff_to_ms(0, 0, 0) == 0
    assert _mmssff_to_ms(1, 0, 0) == 60_000
    assert _mmssff_to_ms(0, 1, 0) == 1_000
    assert _mmssff_to_ms(0, 0, 75) == 1_000  # 75 frames == 1 second


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
