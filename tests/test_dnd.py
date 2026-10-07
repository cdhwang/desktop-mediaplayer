"""Tests for drag-and-drop of media files/folders."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

from PyQt6.QtCore import QMimeData, QUrl

from desktop_music.core.playlist import PlaylistModel
from desktop_music.ui.central_display import CentralDisplay
from desktop_music.ui.dnd import extract_paths, has_media_urls
from desktop_music.ui.playlist_panel import PlaylistPanel


def _mime(paths: list[str]) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
    return mime


# -- helpers ---------------------------------------------------------------


def test_extract_paths_filters_media(tmp_path) -> None:
    mp3 = tmp_path / "a.mp3"
    mp3.write_bytes(b"")
    txt = tmp_path / "note.txt"
    txt.write_bytes(b"")
    mime = _mime([str(mp3), str(txt)])
    assert extract_paths(mime) == [str(mp3)]


def test_extract_paths_keeps_directories(tmp_path) -> None:
    sub = tmp_path / "music"
    sub.mkdir()
    mime = _mime([str(sub)])
    assert extract_paths(mime) == [str(sub)]


def test_has_media_urls(tmp_path) -> None:
    mp4 = tmp_path / "clip.mp4"
    mp4.write_bytes(b"")
    assert has_media_urls(_mime([str(mp4)])) is True
    assert has_media_urls(_mime([str(tmp_path / "x.txt")])) is False


def test_no_urls_returns_empty() -> None:
    assert extract_paths(QMimeData()) == []
    assert has_media_urls(QMimeData()) is False


# -- widget drop signals ---------------------------------------------------


def test_central_display_accepts_drops(qtbot, tmp_path) -> None:
    display = CentralDisplay()
    qtbot.addWidget(display)
    assert display.acceptDrops() is True
    mp3 = tmp_path / "a.mp3"
    mp3.write_bytes(b"")
    with qtbot.waitSignal(display.paths_dropped) as blocker:
        _simulate_drop(display, _mime([str(mp3)]))
    assert blocker.args == [[str(mp3)]]
    display.spectrum._stop_thread()


def test_playlist_panel_accepts_drops(qtbot, tmp_path) -> None:
    panel = PlaylistPanel(PlaylistModel())
    qtbot.addWidget(panel)
    assert panel.acceptDrops() is True
    flac = tmp_path / "b.flac"
    flac.write_bytes(b"")
    with qtbot.waitSignal(panel.paths_dropped) as blocker:
        _simulate_drop(panel, _mime([str(flac)]))
    # empty list -> append position (-1)
    assert blocker.args == [[str(flac)], -1]


def _simulate_drop(widget, mime) -> None:
    """Invoke the widget's dropEvent with a minimal fake event."""
    event = MagicMock()
    event.mimeData.return_value = mime
    widget.dropEvent(event)


# -- window handlers -------------------------------------------------------


def test_window_drop_on_playlist_adds(qtbot, tmp_path) -> None:
    window = _window(qtbot, tmp_path)
    a = tmp_path / "a.mp3"
    a.write_bytes(b"")
    window._on_paths_dropped_add([str(a)])
    assert window.playlist.rowCount() == 1
    window._central_display.spectrum._stop_thread()


def test_window_drop_on_playlist_inserts_at_row(qtbot, tmp_path) -> None:
    from desktop_music.core.playlist import PathRole

    window = _window(qtbot, tmp_path)
    for name in ("a.mp3", "b.mp3", "c.mp3"):
        (tmp_path / name).write_bytes(b"")
    window.playlist.add_paths([str(tmp_path / n) for n in ("a.mp3", "b.mp3", "c.mp3")])
    x = tmp_path / "x.mp3"
    x.write_bytes(b"")
    window._on_paths_dropped_add([str(x)], 1)  # insert before row 1
    m = window.playlist
    names = [os.path.basename(m.data(m.index(i, 0), PathRole)) for i in range(m.rowCount())]
    assert names == ["a.mp3", "x.mp3", "b.mp3", "c.mp3"]
    window._central_display.spectrum._stop_thread()


def test_window_drop_on_playback_adds_and_plays(qtbot, tmp_path) -> None:
    window = _window(qtbot, tmp_path)
    a = tmp_path / "a.mp3"
    a.write_bytes(b"")
    window._controller.play_row = MagicMock()
    window._on_paths_dropped_play([str(a)])
    assert window.playlist.rowCount() == 1
    window._controller.play_row.assert_called_once_with(0)
    window._central_display.spectrum._stop_thread()


def _window(qtbot, tmp_path):
    from desktop_music.core.controller import PlayerController
    from desktop_music.services.backend import PlaybackState
    from desktop_music.services.settings import SettingsStore
    from desktop_music.ui.main_window import MainWindow

    backend = MagicMock()
    backend.get_state.return_value = PlaybackState.IDLE
    backend.get_time.return_value = 0
    backend.get_length.return_value = 0
    backend.get_volume.return_value = 80
    backend.is_muted.return_value = False
    controller = PlayerController(backend=backend)
    controller._timer.stop()
    window = MainWindow(controller=controller, settings=SettingsStore(str(tmp_path / "s.json")))
    qtbot.addWidget(window)
    return window
