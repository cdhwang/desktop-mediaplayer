"""Video surface widget.

A bare native widget that libVLC renders video into. On Linux the window
id (``winId``) is handed to ``MediaPlayer.set_xwindow``. The widget paints
its background black so letterboxing looks clean, and forwards
double-clicks for fullscreen toggling.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QWidget


class VideoSurface(QWidget):
    """Native surface that hosts libVLC video output."""

    double_clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Paint an opaque black background for clean letterboxing. We avoid
        # forcing WA_NativeWindow at construction time: the native handle is
        # created lazily when video is actually embedded (see
        # ``native_window_id``). Allocating native windows eagerly for every
        # instance is unnecessary and unstable under the offscreen platform.
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0))
        self.setPalette(palette)
        self.setMinimumSize(320, 180)

    def native_window_id(self) -> int:
        """Return the platform window handle for VLC embedding.

        Accessing ``winId`` promotes this widget to a native window on
        demand, which is exactly when we need it (i.e. embedding video).
        """
        return int(self.winId())

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)
