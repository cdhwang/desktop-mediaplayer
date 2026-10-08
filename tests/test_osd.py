"""Tests for the transient OSD overlay and the controller ``seeked`` signal."""

from __future__ import annotations

from unittest.mock import MagicMock

from desktop_music.core.controller import PlayerController
from desktop_music.services.backend import PlaybackState
from desktop_music.ui.central_display import CentralDisplay
from desktop_music.ui.main_window import MainWindow
from desktop_music.ui.osd_overlay import OSDOverlay


def _make_controller() -> tuple[PlayerController, MagicMock]:
    backend = MagicMock()
    backend.get_state.return_value = PlaybackState.IDLE
    backend.get_time.return_value = 0
    backend.get_length.return_value = 0
    backend.get_volume.return_value = 50
    backend.set_volume.side_effect = lambda v: max(0, min(100, int(v)))
    backend.is_muted.return_value = False
    controller = PlayerController(backend=backend)
    controller._timer.stop()
    return controller, backend


# -- OSD overlay widget ----------------------------------------------------


def test_osd_shows_and_sets_text(qtbot) -> None:
    parent = CentralDisplay()
    qtbot.addWidget(parent)
    osd = OSDOverlay(parent)
    assert osd.isHidden()
    osd.show_message("Volume  60%")
    assert not osd.isHidden()
    assert osd.text() == "Volume  60%"


def test_osd_transparent_to_mouse(qtbot) -> None:
    from PyQt6.QtCore import Qt

    parent = CentralDisplay()
    qtbot.addWidget(parent)
    osd = OSDOverlay(parent)
    assert osd.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def test_central_display_show_osd(qtbot) -> None:
    display = CentralDisplay()
    qtbot.addWidget(display)
    display.show_osd("Speed  1.50x")
    assert display.osd.text() == "Speed  1.50x"
    assert not display.osd.isHidden()


# -- controller seeked signal ---------------------------------------------


def test_seek_relative_emits_seeked(qtbot) -> None:
    controller, backend = _make_controller()
    backend.get_time.return_value = 20_000
    backend.get_length.return_value = 100_000
    with qtbot.waitSignal(controller.seeked) as blocker:
        controller.seek_relative(5_000)
    # position reported is read back from the backend after the seek
    assert blocker.args == [20_000, 100_000]


def test_seek_to_fraction_emits_seeked(qtbot) -> None:
    controller, backend = _make_controller()
    backend.get_time.return_value = 50_000
    backend.get_length.return_value = 100_000
    with qtbot.waitSignal(controller.seeked):
        controller.seek_to_fraction(0.5)


# -- main window OSD wiring ------------------------------------------------


def _make_window(qtbot) -> MainWindow:
    backend = MagicMock()
    backend.get_state.return_value = PlaybackState.IDLE
    backend.get_time.return_value = 30_000
    backend.get_length.return_value = 120_000
    backend.get_volume.return_value = 60
    backend.set_volume.side_effect = lambda v: max(0, min(100, int(v)))
    backend.is_muted.return_value = False
    controller = PlayerController(backend=backend)
    controller._timer.stop()
    window = MainWindow(controller=controller)
    qtbot.addWidget(window)
    return window


def test_window_osd_suppressed_during_startup(qtbot) -> None:
    window = _make_window(qtbot)
    # OSD must be ready only after construction finishes
    assert window._osd_ready is True
    # nothing was flashed during startup wiring / state restore
    assert window._central_display.osd.isHidden()


def test_volume_change_flashes_osd(qtbot) -> None:
    window = _make_window(qtbot)
    window.controller.backend.get_volume.return_value = 70
    window.controller.set_volume(70)
    assert not window._central_display.osd.isHidden()
    assert "70%" in window._central_display.osd.text()


def test_volume_osd_shows_requested_value_not_lagging_readback(qtbot) -> None:
    """Regression: during playback libVLC's audio_get_volume lags behind
    audio_set_volume, so the OSD must reflect the value we *requested*
    (returned by set_volume), never a stale get_volume read-back."""
    window = _make_window(qtbot)
    backend = window.controller.backend
    # Simulate the real libVLC behaviour: set_volume applies the new value and
    # returns it, but an immediate get_volume still reports the old one.
    backend.set_volume.side_effect = lambda v: v
    backend.get_volume.return_value = 60  # stale value

    window.controller.set_volume(90)

    assert "90%" in window._central_display.osd.text()
    assert "60%" not in window._central_display.osd.text()


def test_change_volume_uses_tracked_value_during_lag(qtbot) -> None:
    """Repeated volume steps must accumulate from the tracked request value,
    not from a lagging get_volume, so successive steps don't stall."""
    window = _make_window(qtbot)
    ctrl = window.controller
    backend = ctrl.backend
    backend.set_volume.side_effect = lambda v: max(0, min(100, v))
    backend.get_volume.return_value = 60  # stale throughout

    ctrl.set_volume(50)  # establish tracked baseline
    ctrl.change_volume(5)
    assert ctrl.volume == 55
    ctrl.change_volume(5)
    assert ctrl.volume == 60
    assert "60%" in window._central_display.osd.text()


def test_mute_flashes_osd(qtbot) -> None:
    window = _make_window(qtbot)
    window.controller.backend.is_muted.return_value = True
    window.controller.toggle_mute()
    assert not window._central_display.osd.isHidden()
    assert window._central_display.osd.text() == "Muted"


def test_seek_flashes_osd(qtbot) -> None:
    window = _make_window(qtbot)
    window.controller.backend.get_time.return_value = 60_000
    window.controller.backend.get_length.return_value = 120_000
    window.controller.seek_relative(5_000)
    assert not window._central_display.osd.isHidden()
    assert window._central_display.osd.text() == "1:00 / 2:00"


def test_rate_change_flashes_osd(qtbot) -> None:
    window = _make_window(qtbot)
    window.controller.backend.get_rate.return_value = 1.5
    window.controller.set_rate(1.5)
    assert not window._central_display.osd.isHidden()
    assert "1.50x" in window._central_display.osd.text()
