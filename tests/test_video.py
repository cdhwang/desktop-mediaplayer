"""Tests for video playback integration (Task 11)."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from desktop_music.constants import is_audio, is_video
from desktop_music.core.controller import PlayerController
from desktop_music.services.backend import PlaybackState
from desktop_music.ui.central_display import PAGE_VIDEO, CentralDisplay
from desktop_music.ui.main_window import MainWindow
from desktop_music.ui.video_surface import VideoSurface


# -- media type detection --------------------------------------------------


def test_media_type_detection() -> None:
    assert is_video("clip.mp4")
    assert is_video("movie.MKV")
    assert is_video("show.avi")
    assert not is_video("song.mp3")
    assert is_audio("song.flac")
    assert not is_audio("clip.mp4")


# -- backend video helpers (mocked) ----------------------------------------


def test_backend_set_video_window_calls_xwindow() -> None:
    from desktop_music.services.backend import VLCBackend

    backend = VLCBackend()
    backend._player = MagicMock()
    backend.set_video_window(12345)
    backend._player.set_xwindow.assert_called_once_with(12345)


def test_backend_has_video() -> None:
    from desktop_music.services.backend import VLCBackend

    backend = VLCBackend()
    backend._player = MagicMock()
    backend._player.video_get_track_count.return_value = 1
    assert backend.has_video() is True
    backend._player.video_get_track_count.return_value = 0
    assert backend.has_video() is False


# -- video surface widget --------------------------------------------------


def test_video_surface_window_id(qtbot) -> None:
    surface = VideoSurface()
    qtbot.addWidget(surface)
    assert isinstance(surface.native_window_id(), int)


def test_video_surface_double_click_signal(qtbot) -> None:
    surface = VideoSurface()
    qtbot.addWidget(surface)
    with qtbot.waitSignal(surface.double_clicked):
        surface.double_clicked.emit()


def test_central_display_has_video_page(qtbot) -> None:
    display = CentralDisplay()
    qtbot.addWidget(display)
    assert display.has_page(PAGE_VIDEO)


# -- main window switches to video page on video media ---------------------


def _window_with_mock_backend(qtbot, tmp_path):
    from desktop_music.services.settings import SettingsStore

    backend = MagicMock()
    backend.get_state.return_value = PlaybackState.IDLE
    backend.get_time.return_value = 0
    backend.get_length.return_value = 0
    backend.get_volume.return_value = 80
    backend.is_muted.return_value = False
    controller = PlayerController(backend=backend)
    controller._timer.stop()
    window = MainWindow(
        controller=controller, settings=SettingsStore(str(tmp_path / "s.json"))
    )
    qtbot.addWidget(window)
    return window, backend


def test_media_changed_switches_to_video_page(qtbot, tmp_path) -> None:
    window, backend = _window_with_mock_backend(qtbot, tmp_path)
    window._on_media_changed("/movies/clip.mp4")
    assert window._central_display.current_page == PAGE_VIDEO
    backend.set_video_window.assert_called_once()
    window._central_display.spectrum._stop_thread()


def test_media_changed_audio_stays_album_art(qtbot, tmp_path) -> None:
    window, _backend = _window_with_mock_backend(qtbot, tmp_path)
    window._on_media_changed("/music/song.mp3")
    assert window._central_display.current_page == "album_art"
    # ensure the background analyzer thread is joined before teardown
    window._central_display.spectrum._stop_thread()


# -- Task 12: track/subtitle helpers + fullscreen UX -----------------------


def test_backend_describe_tracks() -> None:
    from desktop_music.services.backend import VLCBackend

    backend = VLCBackend()
    backend._player = MagicMock()
    backend._player.audio_get_track_description.return_value = [
        (0, b"Disable"),
        (1, b"English"),
    ]
    tracks = backend.audio_tracks()
    assert tracks == [(0, "Disable"), (1, "English")]


def test_backend_set_audio_and_subtitle_track() -> None:
    from desktop_music.services.backend import VLCBackend

    backend = VLCBackend()
    backend._player = MagicMock()
    backend.set_audio_track(2)
    backend._player.audio_set_track.assert_called_once_with(2)
    backend.set_subtitle_track(1)
    backend._player.video_set_spu.assert_called_once_with(1)


def test_backend_subtitle_tracks_empty() -> None:
    from desktop_music.services.backend import VLCBackend

    backend = VLCBackend()
    backend._player = MagicMock()
    backend._player.video_get_spu_description.return_value = None
    assert backend.subtitle_tracks() == []


def test_window_track_menu_items(qtbot, tmp_path) -> None:
    window, backend = _window_with_mock_backend(qtbot, tmp_path)
    backend.audio_tracks.return_value = [(0, "Disable"), (1, "Eng")]
    backend.subtitle_tracks.return_value = [(-1, "Disable")]
    assert window.audio_track_items() == [(0, "Disable"), (1, "Eng")]
    assert window.subtitle_track_items() == [(-1, "Disable")]
    window.select_audio_track(1)
    backend.set_audio_track.assert_called_once_with(1)
    window.select_subtitle_track(-1)
    backend.set_subtitle_track.assert_called_once_with(-1)


def test_fullscreen_enter_exit_toggles_chrome(qtbot, tmp_path) -> None:
    window, _backend = _window_with_mock_backend(qtbot, tmp_path)
    window.show()
    window._enter_fullscreen()
    assert window._control_bar.isHidden()
    assert window._playlist_panel.isHidden()
    window._exit_fullscreen()
    assert not window._control_bar.isHidden()
    assert not window._playlist_panel.isHidden()
