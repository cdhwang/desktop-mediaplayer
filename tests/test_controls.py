"""Tests for commands, formatting, controller dispatch, and control bar (Task 3)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from desktop_music.core import commands as cmd
from desktop_music.core.controller import PlayerController
from desktop_music.core.formatting import format_ms
from desktop_music.services.backend import PlaybackState
from desktop_music.ui.control_bar import ControlBar
from desktop_music.ui.main_window import MainWindow


# -- commands --------------------------------------------------------------


def test_command_registry_unique_ids() -> None:
    ids = [c.id for c in cmd.COMMANDS]
    assert len(ids) == len(set(ids))


def test_default_shortcuts_cover_all_commands() -> None:
    shortcuts = cmd.default_shortcuts()
    assert set(shortcuts) == {c.id for c in cmd.COMMANDS}


# -- formatting ------------------------------------------------------------


@pytest.mark.parametrize(
    "ms,expected",
    [
        (0, "0:00"),
        (5000, "0:05"),
        (65000, "1:05"),
        (3_661_000, "1:01:01"),
        (-1, "0:00"),
    ],
)
def test_format_ms(ms, expected) -> None:
    assert format_ms(ms) == expected


# -- controller ------------------------------------------------------------


def _make_controller() -> tuple[PlayerController, MagicMock]:
    backend = MagicMock()
    backend.get_state.return_value = PlaybackState.IDLE
    backend.get_time.return_value = 0
    backend.get_length.return_value = 0
    backend.get_volume.return_value = 50
    backend.is_muted.return_value = False
    controller = PlayerController(backend=backend)
    controller._timer.stop()  # avoid background polling during tests
    return controller, backend


def test_dispatch_play_pause_calls_backend() -> None:
    controller, backend = _make_controller()
    controller.dispatch(cmd.PLAY_PAUSE)
    backend.toggle_pause.assert_called_once()


def test_dispatch_seek_forward() -> None:
    controller, backend = _make_controller()
    backend.get_time.return_value = 10_000
    controller.dispatch(cmd.SEEK_FORWARD)
    backend.seek.assert_called_once_with(15_000)


def test_dispatch_volume_up() -> None:
    controller, backend = _make_controller()
    backend.get_volume.return_value = 50
    controller.dispatch(cmd.VOLUME_UP)
    backend.set_volume.assert_called_once_with(55)


def test_toggle_mute_emits_signal(qtbot) -> None:
    controller, backend = _make_controller()
    backend.is_muted.return_value = False
    with qtbot.waitSignal(controller.volume_changed):
        controller.toggle_mute()
    backend.set_muted.assert_called_once_with(True)


# -- control bar -----------------------------------------------------------


def test_control_bar_play_signal(qtbot) -> None:
    bar = ControlBar()
    qtbot.addWidget(bar)
    with qtbot.waitSignal(bar.play_pause_clicked):
        bar._play_btn.click()


def test_control_bar_position_updates_labels(qtbot) -> None:
    bar = ControlBar()
    qtbot.addWidget(bar)
    bar.set_position(65_000, 130_000)
    assert bar._time_lbl.text() == "1:05 / 2:10"
    assert bar._seek_slider.value() == 500  # halfway


def test_main_window_wires_control_bar(qtbot) -> None:
    backend = MagicMock()
    backend.get_state.return_value = PlaybackState.IDLE
    backend.get_time.return_value = 0
    backend.get_length.return_value = 0
    backend.get_volume.return_value = 80
    backend.is_muted.return_value = False
    controller = PlayerController(backend=backend)
    controller._timer.stop()
    window = MainWindow(controller=controller)
    qtbot.addWidget(window)
    # clicking play in the bar should reach the backend
    window._control_bar._play_btn.click()
    backend.toggle_pause.assert_called_once()
