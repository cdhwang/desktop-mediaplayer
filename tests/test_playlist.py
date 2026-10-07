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


def test_insert_paths_at_position() -> None:
    m = PlaylistModel()
    m.add_paths(["/a.mp3", "/b.mp3", "/c.mp3"])
    m.insert_paths(1, ["/x.mp3", "/y.mp3"])
    paths = [m.data(m.index(i, 0), PathRole) for i in range(m.rowCount())]
    assert paths == ["/a.mp3", "/x.mp3", "/y.mp3", "/b.mp3", "/c.mp3"]


def test_insert_paths_clamps_and_appends() -> None:
    m = PlaylistModel()
    m.add_paths(["/a.mp3", "/b.mp3"])
    # row past the end appends; add_paths delegates to insert_paths(end)
    m.insert_paths(99, ["/z.mp3"])
    paths = [m.data(m.index(i, 0), PathRole) for i in range(m.rowCount())]
    assert paths == ["/a.mp3", "/b.mp3", "/z.mp3"]


def test_insert_paths_shifts_current() -> None:
    m = PlaylistModel()
    m.add_paths(["/a.mp3", "/b.mp3", "/c.mp3"])
    m.set_current(1)  # playing /b.mp3
    m.insert_paths(0, ["/x.mp3"])  # insert before the playing row
    # cursor shifts so it keeps pointing at /b.mp3
    assert m.current_index == 2
    assert m.data(m.index(m.current_index, 0), PathRole) == "/b.mp3"


def test_insert_paths_after_current_keeps_cursor() -> None:
    m = PlaylistModel()
    m.add_paths(["/a.mp3", "/b.mp3", "/c.mp3"])
    m.set_current(1)
    m.insert_paths(2, ["/x.mp3"])  # insert after the playing row
    assert m.current_index == 1
    assert m.data(m.index(m.current_index, 0), PathRole) == "/b.mp3"


def test_clear_resets() -> None:
    m = PlaylistModel()
    m.add_paths(["/a.mp3", "/b.mp3"])
    m.clear()
    assert m.rowCount() == 0
    assert m.current_index == -1


# -- reorder (drag to move) ------------------------------------------------


def _paths(m: PlaylistModel) -> list[str]:
    return [m.data(m.index(i, 0), PathRole) for i in range(m.rowCount())]


def test_move_row_down() -> None:
    m = PlaylistModel()
    m.add_paths(["/a.mp3", "/b.mp3", "/c.mp3", "/d.mp3"])
    assert m.move_row(0, 2) is True
    assert _paths(m) == ["/b.mp3", "/c.mp3", "/a.mp3", "/d.mp3"]


def test_move_row_up() -> None:
    m = PlaylistModel()
    m.add_paths(["/a.mp3", "/b.mp3", "/c.mp3", "/d.mp3"])
    assert m.move_row(3, 1) is True
    assert _paths(m) == ["/a.mp3", "/d.mp3", "/b.mp3", "/c.mp3"]


def test_move_row_noop_and_bounds() -> None:
    m = PlaylistModel()
    m.add_paths(["/a.mp3", "/b.mp3"])
    assert m.move_row(0, 0) is False
    assert m.move_row(5, 0) is False  # src out of range
    # dst clamps into range; moving last to beyond-end stays last-position move
    assert m.move_row(0, 99) is True
    assert _paths(m) == ["/b.mp3", "/a.mp3"]


def test_move_row_tracks_current_when_moving_current() -> None:
    m = PlaylistModel()
    m.add_paths(["/a.mp3", "/b.mp3", "/c.mp3"])
    m.set_current(0)  # playing /a.mp3
    m.move_row(0, 2)
    assert m.current_index == 2
    assert m.data(m.index(m.current_index, 0), PathRole) == "/a.mp3"


def test_move_row_shifts_current_when_moving_around_it() -> None:
    m = PlaylistModel()
    m.add_paths(["/a.mp3", "/b.mp3", "/c.mp3", "/d.mp3"])
    m.set_current(2)  # playing /c.mp3
    # move a row from before current to after current -> current shifts up
    m.move_row(0, 3)
    assert m.data(m.index(m.current_index, 0), PathRole) == "/c.mp3"

    m2 = PlaylistModel()
    m2.add_paths(["/a.mp3", "/b.mp3", "/c.mp3", "/d.mp3"])
    m2.set_current(1)  # playing /b.mp3
    # move a row from after current to before current -> current shifts down
    m2.move_row(3, 0)
    assert m2.data(m2.index(m2.current_index, 0), PathRole) == "/b.mp3"


def test_panel_reorder_signal_moves_track(qtbot) -> None:
    model = PlaylistModel()
    model.add_paths(["/a.mp3", "/b.mp3", "/c.mp3"])
    panel = PlaylistPanel(model)
    qtbot.addWidget(panel)
    panel.view.reorder_requested.emit(0, 2)
    assert _paths(model) == ["/b.mp3", "/c.mp3", "/a.mp3"]


def test_live_reorder_moves_item_while_dragging(qtbot) -> None:
    """Dragging over a lower row reorders the list immediately (live)."""
    from unittest.mock import MagicMock

    from PyQt6.QtCore import QPointF

    model = PlaylistModel()
    model.add_paths(["/a.mp3", "/b.mp3", "/c.mp3"])
    panel = PlaylistPanel(model)
    qtbot.addWidget(panel)
    view = panel.view
    view.resize(300, 400)
    view.show()
    qtbot.waitExposed(view)

    # Grab row 0 ("/a.mp3").
    view._drag_proxy_row = 0

    # Hover over the lower half of row 2 -> "/a.mp3" should slide to the end.
    rect2 = view.visualRect(panel.proxy.index(2, 0))
    pos = QPointF(float(rect2.center().x()), float(rect2.bottom() - 1))
    event = MagicMock()
    event.source.return_value = view
    event.position.return_value = pos

    view.dragMoveEvent(event)

    assert _paths(model) == ["/b.mp3", "/c.mp3", "/a.mp3"]
    # The dragged-row cursor tracks the item's new position.
    assert view._drag_proxy_row == 2


def test_live_reorder_disabled_while_filtering(qtbot) -> None:
    """No live move happens when a search filter hides rows."""
    from unittest.mock import MagicMock

    from PyQt6.QtCore import QPointF

    model = PlaylistModel()
    model.add_paths(["/a.mp3", "/b.mp3", "/c.mp3"])
    panel = PlaylistPanel(model)
    qtbot.addWidget(panel)
    panel.proxy.set_query("a")  # filter active -> reorder disabled
    view = panel.view
    view._drag_proxy_row = 0

    event = MagicMock()
    event.source.return_value = view
    event.position.return_value = QPointF(10.0, 10.0)
    view.dragMoveEvent(event)

    # list order unchanged
    assert _paths(model) == ["/a.mp3", "/b.mp3", "/c.mp3"]


def test_valid_row_is_drag_enabled() -> None:
    from PyQt6.QtCore import Qt

    m = PlaylistModel()
    m.add_paths(["/a.mp3", "/b.mp3"])
    flags = m.flags(m.index(0, 0))
    assert flags & Qt.ItemFlag.ItemIsDragEnabled
    assert flags & Qt.ItemFlag.ItemIsDropEnabled
    assert flags & Qt.ItemFlag.ItemIsSelectable


def test_proxy_preserves_drag_flags(qtbot) -> None:
    from PyQt6.QtCore import Qt

    model = PlaylistModel()
    model.add_paths(["/a.mp3", "/b.mp3"])
    panel = PlaylistPanel(model)
    qtbot.addWidget(panel)
    pidx = panel.proxy.index(0, 0)
    assert panel.proxy.flags(pidx) & Qt.ItemFlag.ItemIsDragEnabled


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


def test_panel_delete_key_removes_selected(qtbot) -> None:
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtWidgets import QApplication

    model = PlaylistModel()
    model.add_paths(["/a.mp3", "/b.mp3", "/c.mp3"])
    panel = PlaylistPanel(model)
    qtbot.addWidget(panel)

    # select the middle row and press Delete
    panel.view.setCurrentIndex(panel.proxy.index(1, 0))
    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(panel.view, event)

    paths = [t.path for t in model.tracks]
    assert paths == ["/a.mp3", "/c.mp3"]


def test_panel_delete_key_removes_multiple(qtbot) -> None:
    from PyQt6.QtCore import QItemSelectionModel, Qt
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtWidgets import QApplication

    model = PlaylistModel()
    model.add_paths(["/a.mp3", "/b.mp3", "/c.mp3", "/d.mp3"])
    panel = PlaylistPanel(model)
    qtbot.addWidget(panel)

    sel = panel.view.selectionModel()
    for r in (0, 2):
        sel.select(panel.proxy.index(r, 0), QItemSelectionModel.SelectionFlag.Select)
    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(panel.view, event)

    paths = [t.path for t in model.tracks]
    assert paths == ["/b.mp3", "/d.mp3"]


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


# -- distinct cues: playing / selection / focus ---------------------------


def test_playing_role_tracks_current_index() -> None:
    """PlayingRole marks only the current (now-playing) row."""
    from desktop_music.core.playlist import PlayingRole

    model = PlaylistModel()
    model.add_paths(["/a.mp3", "/b.mp3", "/c.mp3"])
    model.set_current(1)

    assert model.data(model.index(0, 0), PlayingRole) is False
    assert model.data(model.index(1, 0), PlayingRole) is True
    assert model.data(model.index(2, 0), PlayingRole) is False


def test_set_current_emits_data_changed_for_playing_cue(qtbot) -> None:
    """Changing current repaints old and new rows via dataChanged(PlayingRole)."""
    from desktop_music.core.playlist import PlayingRole

    model = PlaylistModel()
    model.add_paths(["/a.mp3", "/b.mp3", "/c.mp3"])
    model.set_current(0)

    changed_rows: list[int] = []
    model.dataChanged.connect(
        lambda tl, br, roles: changed_rows.append(tl.row())
        if PlayingRole in roles else None
    )
    model.set_current(2)

    # both the previously-playing row (0) and the new one (2) are repainted
    assert set(changed_rows) == {0, 2}


def test_highlight_current_does_not_change_selection(qtbot) -> None:
    """The now-playing row is independent of the user's selection/focus."""
    model = PlaylistModel()
    model.add_paths(["/a.mp3", "/b.mp3", "/c.mp3"])
    panel = PlaylistPanel(model)
    qtbot.addWidget(panel)

    # user selects/focuses row 0
    panel.view.setCurrentIndex(panel.proxy.index(0, 0))
    assert panel.view.currentIndex().row() == 0

    # playback moves to row 2 -> selection/focus must stay on row 0
    panel.highlight_current(2)
    assert panel.view.currentIndex().row() == 0
