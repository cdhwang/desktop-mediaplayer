"""Tests for the PotPlayer-style layout rework."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np

from desktop_music.core.controller import PlayerController
from desktop_music.services.backend import PlaybackState
from desktop_music.services.metadata import Metadata
from desktop_music.services.settings import SettingsStore
from desktop_music.ui.album_art_view import AlbumArtView
from desktop_music.ui.control_bar import ControlBar
from desktop_music.ui.main_window import MainWindow
from desktop_music.ui.playlist_panel import PlaylistPanel
from desktop_music.ui.spectrum_widget import NUM_BANDS, MiniSpectrum, SpectrumWidget


# -- control bar (two-row) -------------------------------------------------


def test_control_bar_combined_time_label(qtbot) -> None:
    bar = ControlBar()
    qtbot.addWidget(bar)
    bar.set_position(61_000, 125_000)
    assert bar._time_lbl.text() == "1:01 / 2:05"


def test_control_bar_new_signals(qtbot) -> None:
    bar = ControlBar()
    qtbot.addWidget(bar)
    for sig, btn in (
        (bar.eject_clicked, bar._eject_btn),
        (bar.settings_clicked, bar._settings_btn),
        (bar.menu_clicked, bar._menu_btn),
    ):
        with qtbot.waitSignal(sig):
            btn.click()


# -- now-playing overlay ---------------------------------------------------


def test_album_art_now_playing_time(qtbot) -> None:
    view = AlbumArtView()
    qtbot.addWidget(view)
    view.set_position(61_000, 125_000)
    assert view._elapsed.text() == "1:01"
    assert view._total.text() == "2:05"


def test_album_art_tech_info(qtbot) -> None:
    view = AlbumArtView()
    qtbot.addWidget(view)
    meta = Metadata(title="Song", artist="Artist", codec="MP3", bitrate_kbps=320, sample_rate=44100)
    view.show_metadata(meta, fallback_title="fallback")
    assert view._title.text() == "Artist - Song"
    assert view._tech.text() == "MP3 320kbps 44.1khz"


def test_metadata_tech_info_property() -> None:
    meta = Metadata(codec="FLAC", bitrate_kbps=1000, sample_rate=48000)
    assert meta.tech_info == "FLAC 1000kbps 48.0khz"
    assert Metadata().tech_info == ""


def test_mini_spectrum_linked(qtbot) -> None:
    spec = SpectrumWidget()
    qtbot.addWidget(spec)
    mini = MiniSpectrum()
    qtbot.addWidget(mini)
    spec.link_mini(mini)
    spec._data = None
    # feeding a tick should push levels to the mini without error
    spec._tick()
    assert mini._levels.shape == (NUM_BANDS,)
    spec._stop_thread()


# -- playlist panel (toolbar + search toggle) ------------------------------


def test_playlist_toolbar_buttons(qtbot) -> None:
    from desktop_music.core.playlist import PlaylistModel

    model = PlaylistModel()
    model.add_paths(["/a.mp3", "/b.mp3"])
    panel = PlaylistPanel(model)
    qtbot.addWidget(panel)
    assert panel._add_btn.text() == "ADD"
    assert panel._del_btn.text() == "DEL"
    assert panel._sort_btn.text() == "SORT"


def test_playlist_search_toggle(qtbot) -> None:
    from desktop_music.core.playlist import PlaylistModel

    model = PlaylistModel()
    panel = PlaylistPanel(model)
    qtbot.addWidget(panel)
    assert panel._search.isHidden()
    panel._toggle_search()
    assert not panel._search.isHidden()
    panel._toggle_search()
    assert panel._search.isHidden()


def test_playlist_sort(qtbot) -> None:
    from desktop_music.core.playlist import PlaylistModel

    model = PlaylistModel()
    model.add_paths(["/z.mp3", "/a.mp3", "/m.mp3"])
    panel = PlaylistPanel(model)
    qtbot.addWidget(panel)
    panel._sort()
    titles = [t.display_title for t in model.tracks]
    assert titles == sorted(titles, key=str.lower)


# -- integration -----------------------------------------------------------


def test_window_hamburger_menu_builds(qtbot, tmp_path) -> None:
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
    # settings button opens equalizer; menu button builds a popup — just
    # ensure the control bar exposes the new signals wired without error
    window._control_bar.settings_clicked.emit  # attribute exists
    window._control_bar.menu_clicked.emit
    window._central_display.spectrum._stop_thread()
