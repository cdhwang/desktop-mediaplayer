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


# -- metadata must not overwrite cue segment durations/titles --------------


def test_metadata_does_not_overwrite_cue_segment_duration() -> None:
    from desktop_music.core.playlist import PlaylistModel, Track

    file_len = 4_300_000
    m = PlaylistModel()
    m._tracks = [
        Track(path="/x/a.ape", title="T1", artist="A",
              start_ms=0, end_ms=2_000_000, duration_ms=2_000_000),
        Track(path="/x/a.ape", title="T3", artist="A",
              start_ms=4_000_000, end_ms=0, duration_ms=0),  # last -> EOF
        Track(path="/x/plain.mp3"),
    ]
    m._current = 0

    # Metadata extraction reports the WHOLE-file length and album-level tags.
    for row in range(3):
        m.update_track_metadata(
            row, title="WHOLE", artist="VARIOUS", album="Alb",
            duration_ms=file_len if row < 2 else 200_000,
        )

    t = m.tracks
    # mid cue track keeps its segment duration + per-track title
    assert t[0].duration_ms == 2_000_000
    assert t[0].title == "T1"
    # last cue track (end=0) derives length as file_len - start
    assert t[1].duration_ms == file_len - 4_000_000
    assert t[1].title == "T3"
    # ordinary file is enriched normally
    assert t[2].duration_ms == 200_000
    assert t[2].title == "WHOLE"


# -- now-playing display reflects the per-track cue title ------------------


def test_now_playing_title_follows_cue_track(qtbot) -> None:
    """Same backing file, different cue tracks -> distinct now-playing titles."""
    from unittest.mock import patch

    from desktop_music.core.playlist import Track
    from desktop_music.services.metadata import Metadata
    from desktop_music.ui.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    f = "/x/album.ape"
    w._playlist._tracks = [
        Track(path=f, title="Adagio", artist="C", start_ms=0, end_ms=2_000_000),
        Track(path=f, title="Finale", artist="C", start_ms=2_000_000, end_ms=4_000_000),
        Track(path=f, title="Applause", artist="C", start_ms=4_000_000, end_ms=0),
    ]

    shown: list[tuple[str, str]] = []
    w._central_display.show_metadata = lambda meta, fallback_title="": shown.append(
        (meta.title, meta.artist)
    )
    w._central_display.set_lyrics = lambda *a: None
    w._central_display.spectrum.analyze = lambda *a: None
    w._central_display.spectrum.start = lambda *a: None
    w._central_display.spectrum.stop = lambda *a: None

    # read_metadata returns the SAME shared file-level tags for every track
    file_meta = Metadata(title="Whole Album", artist="Various", duration_ms=4_300_000)
    with patch(
        "desktop_music.ui.main_window.read_metadata", return_value=file_meta
    ), patch("desktop_music.ui.main_window.read_lyrics", return_value=""):
        for row in range(3):
            w._playlist.set_current(row)
            w._on_media_changed(f)

    assert shown == [
        ("Adagio", "C"),
        ("Finale", "C"),
        ("Applause", "C"),
    ]


def test_cue_mid_segment_end_advances_to_next(tmp_path) -> None:
    """Reaching a non-final cue segment boundary advances to the next track
    (seeking within the same backing file), not stops.
    """
    from unittest.mock import MagicMock

    from desktop_music.core.controller import PlayerController
    from desktop_music.core.playlist import PlaylistModel, Track
    from desktop_music.services.backend import PlaybackState

    backend = MagicMock()
    backend.get_state.return_value = PlaybackState.PLAYING
    backend.get_length.return_value = 4_300_000
    backend.current_path = "/x/album.ape"
    backend.get_volume.return_value = 50
    backend.is_muted.return_value = False

    controller = PlayerController(backend=backend)
    controller._timer.stop()
    model = PlaylistModel()
    model._tracks = [
        Track(path="/x/album.ape", title="A", start_ms=0, end_ms=2_000_000),
        Track(path="/x/album.ape", title="B", start_ms=2_000_000, end_ms=0),
    ]
    model._current = 0
    controller.set_playlist(model)
    controller.play_row(0, autoplay=True)

    backend.get_time.return_value = 2_000_000
    controller._poll()

    # advanced to track B (same file -> seek to its start), not stopped
    assert model.current_index == 1
    backend.stop.assert_not_called()
    backend.seek.assert_any_call(2_000_000)


def test_cue_last_segment_end_stops_backend(tmp_path) -> None:
    """A cue segment that ends mid-file must stop, not bleed into the next
    segment of the backing file.

    Reproduces the bug where deleting the file's final cue track leaves a new
    "last" track whose end_ms points mid-file; on reaching it, playback used
    to continue playing the backing .ape past the track boundary.
    """
    from unittest.mock import MagicMock

    from desktop_music.core.controller import PlayerController
    from desktop_music.core.playlist import PlaylistModel, Track
    from desktop_music.services.backend import PlaybackState

    backend = MagicMock()
    backend.get_state.return_value = PlaybackState.PLAYING
    backend.get_length.return_value = 4_300_000  # whole .ape length
    backend.current_path = "/x/album.ape"
    backend.get_volume.return_value = 50
    backend.is_muted.return_value = False

    controller = PlayerController(backend=backend)
    controller._timer.stop()
    model = PlaylistModel()
    # single remaining cue track whose segment ends well before EOF
    model._tracks = [
        Track(path="/x/album.ape", title="Last", artist="A",
              start_ms=1_000_000, end_ms=2_000_000)
    ]
    model._current = 0
    controller.set_playlist(model)

    controller.play_row(0, autoplay=True)
    assert controller._seg_end == 2_000_000

    # Simulate reaching the segment boundary during a poll.
    backend.get_time.return_value = 2_000_000
    controller._poll()

    # Playback must be stopped, not left running into the next segment.
    backend.stop.assert_called()


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
