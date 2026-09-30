"""Tests for external subtitles, playback rate, and snapshots (Task 13)."""

from __future__ import annotations

from unittest.mock import MagicMock

from desktop_music.core import commands as cmd
from desktop_music.core.controller import (
    RATE_MAX,
    RATE_MIN,
    RATE_STEP,
    PlayerController,
)
from desktop_music.services.backend import PlaybackState


def _controller():
    backend = MagicMock()
    backend.get_state.return_value = PlaybackState.IDLE
    backend.get_time.return_value = 0
    backend.get_length.return_value = 0
    backend.get_rate.return_value = 1.0
    ctrl = PlayerController(backend=backend)
    ctrl._timer.stop()
    return ctrl, backend


# -- backend external subtitle / snapshot ----------------------------------


def test_backend_add_subtitle_file() -> None:
    from desktop_music.services.backend import VLCBackend

    backend = VLCBackend()
    backend._player = MagicMock()
    backend._player.add_slave.return_value = 0
    assert backend.add_subtitle_file("/subs/movie.srt") is True
    assert backend._player.add_slave.called


def test_backend_take_snapshot() -> None:
    from desktop_music.services.backend import VLCBackend

    backend = VLCBackend()
    backend._player = MagicMock()
    backend._player.video_take_snapshot.return_value = 0
    assert backend.take_snapshot("/tmp/shot.png") is True
    backend._player.video_take_snapshot.assert_called_once_with(0, "/tmp/shot.png", 0, 0)


# -- controller rate control -----------------------------------------------


def test_set_rate_calls_backend(qtbot) -> None:
    ctrl, backend = _controller()
    backend.get_rate.return_value = 1.5
    with qtbot.waitSignal(ctrl.rate_changed):
        ctrl.set_rate(1.5)
    backend.set_rate.assert_called_once_with(1.5)


def test_rate_clamped() -> None:
    ctrl, backend = _controller()
    ctrl.set_rate(99.0)
    backend.set_rate.assert_called_with(RATE_MAX)
    ctrl.set_rate(0.01)
    backend.set_rate.assert_called_with(RATE_MIN)


def test_change_rate_and_reset() -> None:
    ctrl, backend = _controller()
    backend.get_rate.return_value = 1.0
    ctrl.change_rate(RATE_STEP)
    backend.set_rate.assert_called_with(1.0 + RATE_STEP)
    ctrl.reset_rate()
    backend.set_rate.assert_called_with(1.0)


def test_dispatch_rate_commands() -> None:
    ctrl, backend = _controller()
    backend.get_rate.return_value = 1.0
    ctrl.dispatch(cmd.RATE_UP)
    backend.set_rate.assert_called_with(1.0 + RATE_STEP)
    ctrl.dispatch(cmd.RATE_RESET)
    backend.set_rate.assert_called_with(1.0)


# -- window snapshot / subtitle flow ---------------------------------------


def test_window_take_snapshot(qtbot, tmp_path, monkeypatch) -> None:
    from desktop_music.services.settings import SettingsStore
    from desktop_music.ui.main_window import MainWindow

    backend = MagicMock()
    backend.get_state.return_value = PlaybackState.IDLE
    backend.get_time.return_value = 0
    backend.get_length.return_value = 0
    backend.get_volume.return_value = 80
    backend.is_muted.return_value = False
    backend.take_snapshot.return_value = True
    controller = PlayerController(backend=backend)
    controller._timer.stop()
    window = MainWindow(
        controller=controller, settings=SettingsStore(str(tmp_path / "s.json"))
    )
    qtbot.addWidget(window)

    target = str(tmp_path / "shot.png")
    monkeypatch.setattr(
        "desktop_music.ui.main_window.QFileDialog.getSaveFileName",
        lambda *a, **k: (target, "PNG Image (*.png)"),
    )
    result = window.take_snapshot()
    assert result == target
    backend.take_snapshot.assert_called_once_with(target)
