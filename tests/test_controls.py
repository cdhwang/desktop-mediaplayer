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


def test_seek_slider_click_jumps_to_position(qtbot) -> None:
    from PyQt6.QtCore import QEvent, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent

    bar = ControlBar()
    qtbot.addWidget(bar)
    bar.show()
    qtbot.waitExposed(bar)

    slider = bar._seek_slider
    slider.setFixedWidth(1000)
    slider.resize(1000, slider.height())

    results: list[float] = []
    bar.seek_requested.connect(results.append)

    # Click near the right edge -> should seek near the end, not a tiny step.
    x = 900
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(x, 5),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(x, 5),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    slider.mousePressEvent(press)
    slider.mouseReleaseEvent(release)

    assert results, "seek_requested was not emitted"
    assert results[-1] > 0.8  # jumped near the clicked position


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


# -- repeat radio controls -------------------------------------------------


def _make_window(qtbot, tmp_path) -> MainWindow:
    from desktop_music.services.settings import SettingsStore

    backend = MagicMock()
    backend.get_state.return_value = PlaybackState.IDLE
    backend.get_time.return_value = 0
    backend.get_length.return_value = 0
    backend.get_volume.return_value = 80
    backend.is_muted.return_value = False
    controller = PlayerController(backend=backend)
    controller._timer.stop()
    # Isolate persistence so tests never read/write the real state.json.
    settings = SettingsStore(path=str(tmp_path / "state.json"))
    window = MainWindow(controller=controller, settings=settings)
    qtbot.addWidget(window)
    return window


def test_repeat_menu_is_exclusive_radio(qtbot, tmp_path) -> None:
    window = _make_window(qtbot, tmp_path)
    actions = window._repeat_actions
    assert set(actions) == {"none", "all", "one"}
    assert window._repeat_group.isExclusive()
    for action in actions.values():
        assert action.isCheckable()
    checked = [k for k, a in actions.items() if a.isChecked()]
    assert checked == ["none"]


def test_repeat_menu_action_sets_mode(qtbot, tmp_path) -> None:
    from desktop_music.core.playmode import RepeatMode

    window = _make_window(qtbot, tmp_path)
    window._repeat_actions["one"].trigger()
    assert window.controller.play_mode.repeat == RepeatMode.ONE
    assert window._repeat_actions["one"].isChecked()


def test_control_bar_repeat_buttons_are_radio(qtbot, tmp_path) -> None:
    window = _make_window(qtbot, tmp_path)
    bar = window._control_bar
    assert set(bar._repeat_buttons) == {"none", "all", "one"}
    for btn in bar._repeat_buttons.values():
        assert btn.isCheckable()
    # exactly the active mode (none) is checked initially
    checked = [m for m, b in bar._repeat_buttons.items() if b.isChecked()]
    assert checked == ["none"]


def test_control_bar_repeat_button_selects_mode(qtbot, tmp_path) -> None:
    from desktop_music.core.playmode import RepeatMode

    window = _make_window(qtbot, tmp_path)
    bar = window._control_bar
    # click the "all" button -> controller switches to repeat-all and only
    # that button stays checked
    bar._repeat_all_btn.click()
    assert window.controller.play_mode.repeat == RepeatMode.ALL
    checked = [m for m, b in bar._repeat_buttons.items() if b.isChecked()]
    assert checked == ["all"]
    # pick "one" -> exclusive switch
    bar._repeat_one_btn.click()
    assert window.controller.play_mode.repeat == RepeatMode.ONE
    checked = [m for m, b in bar._repeat_buttons.items() if b.isChecked()]
    assert checked == ["one"]


def test_control_bar_and_menu_stay_in_sync(qtbot, tmp_path) -> None:
    window = _make_window(qtbot, tmp_path)
    # selecting via the menu reflects on the control-bar buttons…
    window._repeat_actions["all"].trigger()
    assert window._control_bar._repeat_all_btn.isChecked()
    assert not window._control_bar._repeat_none_btn.isChecked()
    # …and selecting via the control bar reflects on the menu
    window._control_bar._repeat_one_btn.click()
    assert window._repeat_actions["one"].isChecked()
    assert not window._repeat_actions["all"].isChecked()
