"""Tests for dragging the window via the central playback area."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent

from desktop_music.ui.central_display import CentralDisplay


def _press_event(global_pos: QPoint) -> QMouseEvent:
    local = QPointF(1.0, 1.0)
    return QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        local,
        QPointF(global_pos),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def _move_event(global_pos: QPoint) -> QMouseEvent:
    local = QPointF(1.0, 1.0)
    return QMouseEvent(
        QMouseEvent.Type.MouseMove,
        local,
        QPointF(global_pos),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def test_drag_moves_window_manual_fallback(qtbot) -> None:
    display = CentralDisplay()
    qtbot.addWidget(display)
    display.show()
    qtbot.waitExposed(display)

    window = display.window()
    start = window.frameGeometry().topLeft()

    assert display.start_window_drag(_press_event(start + QPoint(10, 10)))
    # On platforms where the native move succeeds there is nothing to assert
    # about geometry; only exercise the manual path when it actually engaged.
    if display._drag_active:
        moved = display.continue_window_drag(_move_event(start + QPoint(60, 40)))
        assert moved
        new_pos = window.frameGeometry().topLeft()
        assert new_pos.x() == start.x() + 50
        assert new_pos.y() == start.y() + 30
        assert display.end_window_drag(_move_event(start + QPoint(60, 40)))


def test_manual_drag_math_moves_window(qtbot) -> None:
    """Exercise the manual-fallback geometry math deterministically."""
    display = CentralDisplay()
    qtbot.addWidget(display)
    display.show()
    qtbot.waitExposed(display)

    window = display.window()
    start = window.frameGeometry().topLeft()

    # Prime the manual drag state as start_window_drag's fallback would,
    # bypassing the platform-dependent native move.
    display._drag_active = True
    display._drag_offset = QPoint(10, 10)

    assert display.continue_window_drag(_move_event(start + QPoint(60, 40)))
    new_pos = window.frameGeometry().topLeft()
    assert new_pos.x() == start.x() + 50
    assert new_pos.y() == start.y() + 30
    assert display.end_window_drag(_move_event(start + QPoint(60, 40)))
    assert display._drag_active is False


def test_drag_disabled_when_fullscreen(qtbot) -> None:
    display = CentralDisplay()
    qtbot.addWidget(display)
    display.showFullScreen()
    qtbot.waitExposed(display)

    start = display.window().frameGeometry().topLeft()
    assert display.start_window_drag(_press_event(start + QPoint(10, 10))) is False


def test_right_click_does_not_drag(qtbot) -> None:
    display = CentralDisplay()
    qtbot.addWidget(display)
    display.show()
    qtbot.waitExposed(display)

    pos = display.window().frameGeometry().topLeft()
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(1.0, 1.0),
        QPointF(pos),
        Qt.MouseButton.RightButton,
        Qt.MouseButton.RightButton,
        Qt.KeyboardModifier.NoModifier,
    )
    assert display.start_window_drag(event) is False
