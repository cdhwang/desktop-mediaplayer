"""Tests for the playlist model, panel, and navigation (Task 4)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

from desktop_music.core.controller import PlayerController
from desktop_music.core.playlist import PathRole, PlaylistModel, Track
from desktop_music.services.backend import PlaybackState
from desktop_music.ui.playlist_panel import PlaylistPanel


# -- Track -----------------------------------------------------------------


def test_track_display_title_variants() -> None:
    assert Track(path="/a/b/song.mp3").display_title == "song.mp3"
    assert Track(path="x", title="Title").display_title == "Title"
    assert Track(path="x", title="Title", artist="Artist").display_title == "Artist - Title"


# -- model add / remove ----------------------------------------------------


def test_add_media_and_reject_non_media() -> None:
    m = PlaylistModel()
    assert m.add_path("/music/a.mp3") == 1
    assert m.add_path("/docs/readme.txt") == 0
    assert m.rowCount() == 1
    assert m.current_index == 0  # first add sets current


def test_add_paths_scans_directory(tmp_path) -> None:
    (tmp_path / "a.mp3").write_bytes(b"")
    (tmp_path / "b.flac").write_bytes(b"")
    (tmp_path / "note.txt").write_bytes(b"")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.wav").write_bytes(b"")
    m = PlaylistModel()
    count = m.add_paths([str(tmp_path)])
    assert count == 3
    paths = [m.data(m.index(i, 0), PathRole) for i in range(m.rowCount())]
    assert all(os.path.splitext(p)[1] in {".mp3", ".flac", ".wav"} for p in paths)


def test_remove_row_adjusts_current() -> None:
    m = PlaylistModel()
    m.add_paths(["/a.mp3", "/b.mp3", "/c.mp3"])
    m.set_current(2)
    m.remove_row(0)  # removing before current shifts it down
    assert m.current_index == 1
    assert m.rowCount() == 2


def test_clear_resets() -> None:
    m = PlaylistModel()
    m.add_paths(["/a.mp3", "/b.mp3"])
    m.clear()
    assert m.rowCount() == 0
    assert m.current_index == -1


# -- navigation ------------------------------------------------------------


def test_next_previous_wrap() -> None:
    m = PlaylistModel()
    m.add_paths(["/a.mp3", "/b.mp3", "/c.mp3"])
    m.set_current(0)
    assert m.next_index() == 1
    m.set_current(2)
    assert m.next_index(wrap=True) == 0
    assert m.next_index(wrap=False) == -1
    m.set_current(0)
    assert m.previous_index(wrap=True) == 2
    assert m.previous_index(wrap=False) == -1


def test_empty_navigation() -> None:
    m = PlaylistModel()
    assert m.next_index() == -1
    assert m.previous_index() == -1


# -- controller integration ------------------------------------------------


def _controller_with_playlist(paths):
    backend = MagicMock()
    backend.get_state.return_value = PlaybackState.IDLE
    backend.get_time.return_value = 0
    backend.get_length.return_value = 0
    backend.get_volume.return_value = 50
    backend.is_muted.return_value = False
    ctrl = PlayerController(backend=backend)
    ctrl._timer.stop()
    model = PlaylistModel()
    model.add_paths(paths)
    ctrl.set_playlist(model)
    return ctrl, backend, model


def test_play_row_loads_track() -> None:
    ctrl, backend, model = _controller_with_playlist(["/a.mp3", "/b.mp3"])
    ctrl.play_row(1)
    backend.load.assert_called_once_with("/b.mp3")
    assert model.current_index == 1


def test_next_advances_and_wraps() -> None:
    ctrl, backend, model = _controller_with_playlist(["/a.mp3", "/b.mp3"])
    model.set_current(1)
    ctrl.next()
    backend.load.assert_called_with("/a.mp3")  # wrapped to first
    assert model.current_index == 0


def test_auto_advance_on_end() -> None:
    ctrl, backend, model = _controller_with_playlist(["/a.mp3", "/b.mp3"])
    model.set_current(0)
    ctrl.playback_ended.emit()
    backend.load.assert_called_with("/b.mp3")
    assert model.current_index == 1


# -- panel -----------------------------------------------------------------


def test_panel_double_click_emits(qtbot) -> None:
    model = PlaylistModel()
    model.add_paths(["/a.mp3", "/b.mp3"])
    panel = PlaylistPanel(model)
    qtbot.addWidget(panel)
    with qtbot.waitSignal(panel.track_activated) as blocker:
        idx = model.index(1, 0)
        panel.view.doubleClicked.emit(idx)
    assert blocker.args == [1]


# -- scan_dir_flat (CLI open-in-folder) ------------------------------------


def test_scan_dir_flat_is_nonrecursive_sorted_absolute(tmp_path) -> None:
    from desktop_music.core.playlist import scan_dir_flat

    (tmp_path / "b.mp3").write_bytes(b"")
    (tmp_path / "a.flac").write_bytes(b"")
    (tmp_path / "c.mp4").write_bytes(b"")
    (tmp_path / "note.txt").write_bytes(b"")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "deep.mp3").write_bytes(b"")

    found = scan_dir_flat(str(tmp_path))
    assert [os.path.basename(p) for p in found] == ["a.flac", "b.mp3", "c.mp4"]
    assert all(os.path.isabs(p) for p in found)


def test_scan_dir_flat_missing_directory() -> None:
    from desktop_music.core.playlist import scan_dir_flat

    assert scan_dir_flat("/no/such/dir/hopefully") == []
