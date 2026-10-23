"""Tests for PlayerController remote (browser-playback) mode.

Remote mode makes the browser the sole audio source: the desktop backend is
muted and only loads tracks (never auto-plays), and the browser's reported
position/state is surfaced through the state snapshot.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from desktop_music.core.controller import PlayerController
from desktop_music.services.backend import PlaybackState
from desktop_music.services.remote import state as rstate


def _make_controller():
    backend = MagicMock()
    backend.get_state.return_value = PlaybackState.IDLE
    backend.get_time.return_value = 0
    backend.get_length.return_value = 0
    backend.get_volume.return_value = 50
    backend.is_muted.return_value = False
    backend.is_playing.return_value = False
    controller = PlayerController(backend=backend)
    controller._timer.stop()
    return controller, backend


class FakeTrack:
    def __init__(self, path, start_ms=0, end_ms=0):
        self.path = path
        self.start_ms = start_ms
        self.end_ms = end_ms

    @property
    def is_cue_track(self):
        return self.start_ms > 0 or self.end_ms > 0


class FakePlaylist:
    def __init__(self, tracks):
        self._tracks = tracks
        self.current_index = -1

    def rowCount(self):  # noqa: N802
        return len(self._tracks)

    def track_at(self, row):
        return self._tracks[row] if 0 <= row < len(self._tracks) else None

    def current_track(self):
        return self.track_at(self.current_index)

    def set_current(self, row):
        self.current_index = row


def test_remote_mode_mutes_backend():
    controller, backend = _make_controller()
    assert controller.remote_mode is False
    controller.set_remote_mode(True)
    assert controller.remote_mode is True
    backend.set_muted.assert_called_with(True)


def test_remote_mode_restores_mute_on_disable():
    controller, backend = _make_controller()
    backend.is_muted.return_value = False  # desktop was unmuted before remote
    controller.set_remote_mode(True)
    backend.set_muted.reset_mock()
    controller.set_remote_mode(False)
    # Restores the pre-remote state (unmuted).
    backend.set_muted.assert_called_with(False)


def test_remote_mode_pauses_if_playing():
    controller, backend = _make_controller()
    backend.is_playing.return_value = True
    controller.set_remote_mode(True)
    backend.pause.assert_called_once()


def test_remote_mode_is_idempotent():
    controller, backend = _make_controller()
    controller.set_remote_mode(True)
    backend.set_muted.reset_mock()
    controller.set_remote_mode(True)  # already on
    backend.set_muted.assert_not_called()


def test_play_row_loads_only_in_remote_mode():
    controller, backend = _make_controller()
    playlist = FakePlaylist([FakeTrack("/a.flac")])
    controller.set_playlist(playlist)
    controller.set_remote_mode(True)
    backend.play.reset_mock()
    controller.play_row(0)
    # Track is loaded but playback is NOT started.
    backend.load.assert_called_with("/a.flac")
    backend.play.assert_not_called()


def test_play_row_plays_when_not_remote():
    controller, backend = _make_controller()
    playlist = FakePlaylist([FakeTrack("/a.flac")])
    controller.set_playlist(playlist)
    controller.play_row(0)
    backend.load.assert_called_with("/a.flac")
    backend.play.assert_called()


def test_remote_report_ignored_when_off():
    controller, _ = _make_controller()
    controller.set_remote_report(position_ms=5000, length_ms=10000, state="playing")
    assert controller.remote_report is None


def test_remote_report_stored_when_on():
    controller, _ = _make_controller()
    controller.set_remote_mode(True)
    controller.set_remote_report(position_ms=5000, length_ms=10000, state="playing")
    assert controller.remote_report == {
        "position_ms": 5000,
        "length_ms": 10000,
        "state": "playing",
    }


def test_snapshot_prefers_browser_report_in_remote_mode():
    controller, backend = _make_controller()
    backend.get_time.return_value = 0        # desktop paused at 0
    backend.get_length.return_value = 0
    backend.get_state.return_value = PlaybackState.PAUSED
    playlist = FakePlaylist([FakeTrack("/a.flac")])
    controller.set_playlist(playlist)
    playlist.set_current(0)
    controller.set_remote_mode(True)
    controller.set_remote_report(position_ms=42000, length_ms=200000, state="playing")

    snap = rstate.build_state_snapshot(controller, playlist)
    assert snap["remote_mode"] is True
    assert snap["position_ms"] == 42000
    assert snap["length_ms"] == 200000
    assert snap["state"] == "playing"


def test_snapshot_uses_backend_when_not_remote():
    controller, backend = _make_controller()
    backend.get_time.return_value = 1234
    backend.get_length.return_value = 5678
    backend.get_state.return_value = PlaybackState.PLAYING
    playlist = FakePlaylist([FakeTrack("/a.flac")])
    controller.set_playlist(playlist)
    playlist.set_current(0)

    snap = rstate.build_state_snapshot(controller, playlist)
    assert snap["remote_mode"] is False
    assert snap["position_ms"] == 1234
    assert snap["length_ms"] == 5678
