"""Smoke tests for the application shell (Task 1)."""

from __future__ import annotations

from desktop_music.constants import (
    is_audio,
    is_media,
    is_video,
)
from desktop_music.ui.main_window import MainWindow


def test_import_package() -> None:
    import desktop_music

    assert desktop_music.__version__


def test_main_window_creates(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.windowTitle() == "Desktop Music"


def test_extension_helpers() -> None:
    assert is_audio("song.MP3")
    assert is_audio("track.flac")
    assert not is_audio("clip.mp4")

    assert is_video("clip.mp4")
    assert is_video("movie.MKV")
    assert not is_video("song.mp3")

    assert is_media("song.mp3")
    assert is_media("clip.avi")
    assert not is_media("notes.txt")


# -- Task 15: menu bar, theme, full integration ----------------------------


def _integration_window(qtbot, tmp_path):
    from unittest.mock import MagicMock

    from desktop_music.core.controller import PlayerController
    from desktop_music.services.backend import PlaybackState
    from desktop_music.services.settings import SettingsStore

    backend = MagicMock()
    backend.get_state.return_value = PlaybackState.IDLE
    backend.get_time.return_value = 0
    backend.get_length.return_value = 0
    backend.get_volume.return_value = 80
    backend.is_muted.return_value = False
    backend.audio_tracks.return_value = [(0, "Track 1")]
    backend.subtitle_tracks.return_value = []
    controller = PlayerController(backend=backend)
    controller._timer.stop()
    window = MainWindow(
        controller=controller, settings=SettingsStore(str(tmp_path / "s.json"))
    )
    qtbot.addWidget(window)
    return window, backend


def test_context_menu_has_expected_groups(qtbot, tmp_path) -> None:
    window, _backend = _integration_window(qtbot, tmp_path)
    # the menu bar is hidden; entries now live in the context menu
    assert window.menuBar().isHidden()
    titles = [m.title() for m in window._menu_groups]
    assert "&File" in titles
    assert "&View" in titles
    assert "&Playback" in titles
    assert "&Tools" in titles


def test_context_menu_builds_and_contains_groups(qtbot, tmp_path) -> None:
    window, _backend = _integration_window(qtbot, tmp_path)
    popup = window._build_main_menu()
    submenu_titles = [a.menu().title() for a in popup.actions() if a.menu()]
    assert submenu_titles == ["&File", "&View", "&Playback", "&Tools"]


def test_theme_applied(qtbot) -> None:
    from desktop_music.app import create_app

    app = create_app([])
    assert "background-color" in app.styleSheet()


def test_view_menu_switches_pages(qtbot, tmp_path) -> None:
    window, _backend = _integration_window(qtbot, tmp_path)
    window.show_lyrics()
    assert window._central_display.current_page == "lyrics"
    window.show_album_art()
    assert window._central_display.current_page == "album_art"


def test_audio_track_menu_populates(qtbot, tmp_path) -> None:
    window, _backend = _integration_window(qtbot, tmp_path)
    window._populate_audio_menu()
    labels = [a.text() for a in window._audio_menu.actions()]
    assert labels == ["Track 1"]
    window._central_display.spectrum._stop_thread()


def test_window_title_formatting() -> None:
    from desktop_music.constants import APP_NAME
    from desktop_music.services.metadata import Metadata

    fmt = MainWindow._format_window_title
    # title + artist
    assert fmt(Metadata(title="Song", artist="Band"), "file.mp3") == (
        f"Song - Band \u2014 {APP_NAME}"
    )
    # title only
    assert fmt(Metadata(title="Song"), "file.mp3") == f"Song \u2014 {APP_NAME}"
    # no tags -> fall back to the file/display name
    assert fmt(Metadata(), "file.mp3") == f"file.mp3 \u2014 {APP_NAME}"
    # nothing at all -> bare app name
    assert fmt(Metadata(), "") == APP_NAME


def test_media_change_updates_window_title(qtbot, tmp_path) -> None:
    from unittest.mock import patch

    from desktop_music.constants import APP_NAME
    from desktop_music.services.metadata import Metadata

    window, _backend = _integration_window(qtbot, tmp_path)
    with patch(
        "desktop_music.ui.main_window.read_metadata",
        return_value=Metadata(title="Hello", artist="World"),
    ), patch("desktop_music.ui.main_window.read_lyrics", return_value=""):
        window._on_media_changed("/music/track.mp3")
    assert window.windowTitle() == f"Hello - World \u2014 {APP_NAME}"
    # clearing the current media restores the bare app name
    window._on_media_changed(None)
    assert window.windowTitle() == APP_NAME
    window._central_display.spectrum._stop_thread()


def test_central_display_context_menu_signal(qtbot) -> None:
    from PyQt6.QtCore import QPoint

    from desktop_music.ui.central_display import CentralDisplay

    display = CentralDisplay()
    qtbot.addWidget(display)
    received: list = []
    display.context_menu_requested.connect(received.append)
    display.context_menu_requested.emit(QPoint(10, 10))
    assert received == [QPoint(10, 10)]

