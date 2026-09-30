"""Tests for playlist search/filtering (Task 7)."""

from __future__ import annotations

from desktop_music.core.playlist import PlaylistModel
from desktop_music.core.playlist_filter import PlaylistFilterProxy
from desktop_music.ui.playlist_panel import PlaylistPanel


def _model_with_meta() -> PlaylistModel:
    m = PlaylistModel()
    m.add_paths(["/music/alpha.mp3", "/music/beta.mp3", "/music/gamma.mp3"])
    m.update_track_metadata(0, title="Sunrise", artist="The Dawn", album="Morning")
    m.update_track_metadata(1, title="Midnight", artist="The Dawn", album="Evening")
    m.update_track_metadata(2, title="Noon", artist="Solar", album="Morning")
    return m


def test_empty_query_shows_all() -> None:
    proxy = PlaylistFilterProxy(_model_with_meta())
    proxy.set_query("")
    assert proxy.rowCount() == 3


def test_filter_by_title() -> None:
    proxy = PlaylistFilterProxy(_model_with_meta())
    proxy.set_query("mid")
    assert proxy.rowCount() == 1
    assert proxy.to_source_row(0) == 1


def test_filter_by_artist() -> None:
    proxy = PlaylistFilterProxy(_model_with_meta())
    proxy.set_query("the dawn")
    assert proxy.rowCount() == 2


def test_filter_by_album() -> None:
    proxy = PlaylistFilterProxy(_model_with_meta())
    proxy.set_query("morning")
    assert proxy.rowCount() == 2


def test_filter_by_filename() -> None:
    proxy = PlaylistFilterProxy(_model_with_meta())
    proxy.set_query("gamma")
    assert proxy.rowCount() == 1
    assert proxy.to_source_row(0) == 2


def test_filter_case_insensitive() -> None:
    proxy = PlaylistFilterProxy(_model_with_meta())
    proxy.set_query("SUNRISE")
    assert proxy.rowCount() == 1


def test_row_mapping_roundtrip() -> None:
    proxy = PlaylistFilterProxy(_model_with_meta())
    proxy.set_query("the dawn")  # rows 0 and 1 remain
    # source row 1 maps to some proxy row and back
    proxy_row = proxy.from_source_row(1)
    assert proxy_row >= 0
    assert proxy.to_source_row(proxy_row) == 1


def test_panel_search_filters_view(qtbot) -> None:
    panel = PlaylistPanel(_model_with_meta())
    qtbot.addWidget(panel)
    panel._search.setText("noon")
    assert panel.proxy.rowCount() == 1
    # activating the single filtered row emits the correct SOURCE row
    with qtbot.waitSignal(panel.track_activated) as blocker:
        idx = panel.proxy.index(0, 0)
        panel.view.doubleClicked.emit(idx)
    assert blocker.args == [2]
