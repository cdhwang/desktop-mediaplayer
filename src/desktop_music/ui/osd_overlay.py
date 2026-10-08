"""Transient on-screen display (OSD) overlay.

A small translucent label pinned to the top-left of its parent widget that
flashes short status messages — volume changes, seek positions, playback
rate, mute, etc. — and then fades away. It mirrors PotPlayer's behaviour of
briefly confirming *what value* an action changed something to, so the user
isn't left guessing after a keyboard/wheel action.

The overlay is a child of the central display area and never steals mouse
events (it is transparent to the mouse), so it never interferes with
dragging, double-click-to-pause, or wheel-to-volume.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QLabel, QWidget

# How long a message stays fully visible before hiding (ms).
_HOLD_MS = 1200


class OSDOverlay(QLabel):
    """A transient status label anchored to the top-left of its parent."""

    # margin from the parent's top-left corner, in pixels
    _MARGIN = 16

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        # never intercept mouse events meant for the display beneath us
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setStyleSheet(
            "QLabel {"
            "  color: #ffffff;"
            "  background-color: rgba(0, 0, 0, 160);"
            "  border-radius: 6px;"
            "  padding: 6px 12px;"
            "  font-size: 15px;"
            "  font-weight: bold;"
            "}"
        )
        self.hide()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, text: str) -> None:
        """Display *text* at the top-left and (re)start the hide timer."""
        self.setText(text)
        self.adjustSize()
        self.move(self._MARGIN, self._MARGIN)
        self.raise_()
        self.show()
        self._timer.start(_HOLD_MS)
