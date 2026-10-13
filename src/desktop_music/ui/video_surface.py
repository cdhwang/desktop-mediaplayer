"""Video surface widget.

libVLC renders video into a *native* child window. On every platform
libVLC creates its own video child window inside that handle, and that
child window receives the OS-level mouse/keyboard messages directly —
so a plain ``QWidget`` embedding libVLC never sees double-clicks, wheel,
or right-click events (they are swallowed by libVLC's child window).

To make interaction work regardless of platform (notably Windows, where
the libVLC child HWND steals all input), this widget is a *container*
with two children stacked on top of each other:

* ``_video_host`` — the native window libVLC actually draws into
  (handed to ``set_hwnd`` / ``set_xwindow`` / ``set_nsobject``).
* ``_overlay`` — a transparent, mouse-opaque widget placed on top of the
  video. It does not paint anything (so the video shows through) but it
  *does* receive mouse events, which it translates into the widget's
  double-click / wheel / context-menu signals.

Because the overlay is a non-native Qt widget layered above the video
host, Qt delivers input to it before libVLC's child window can consume
it.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QWidget


class _VideoHost(QWidget):
    """Opaque native surface that libVLC renders video into."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0))
        self.setPalette(palette)


class VideoSurface(QWidget):
    """Container hosting libVLC video output plus a mouse overlay."""

    double_clicked = pyqtSignal()
    # emitted on mouse-wheel: +1 per up notch, -1 per down notch
    volume_step = pyqtSignal(int)
    # emitted on right-click, with the global position for the menu
    context_menu_requested = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 180)

        # Black container background so letterboxing looks clean even before
        # the video host is sized/painted.
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0))
        self.setPalette(palette)

        # The native window libVLC draws into. Sized to fill the container.
        self._video_host = _VideoHost(self)

        # Transparent overlay stacked above the video host. It must NOT be a
        # native window (otherwise it would stack behind the video host's
        # native child); as a regular Qt widget it is composited on top and
        # receives mouse events before libVLC's child window can grab them.
        self._overlay = QWidget(self)
        self._overlay.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, False
        )
        # Paint nothing so the video shows through. A translucent background
        # with full transparency keeps the overlay invisible.
        self._overlay.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._overlay.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._overlay.setStyleSheet("background: transparent;")
        # Route the overlay's input events through our own handlers.
        self._overlay.installEventFilter(self)

        self._layout_children()

    # -- layout ------------------------------------------------------------

    def _layout_children(self) -> None:
        rect = self.rect()
        self._video_host.setGeometry(rect)
        self._overlay.setGeometry(rect)
        self._overlay.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._layout_children()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        self._layout_children()

    # -- VLC embedding -----------------------------------------------------

    def native_window_id(self) -> int:
        """Return the platform window handle libVLC should render into.

        This is the *video host* child, not the container. Accessing
        ``winId`` promotes it to a native window on demand.
        """
        return int(self._video_host.winId())

    # -- input: delivered via the transparent overlay ----------------------

    def eventFilter(self, obj, event):  # noqa: N802 (Qt override)
        from PyQt6.QtCore import QEvent

        if obj is self._overlay:
            etype = event.type()
            if etype == QEvent.Type.MouseButtonDblClick:
                self.double_clicked.emit()
                event.accept()
                return True
            if etype == QEvent.Type.Wheel:
                notches = event.angleDelta().y()
                if notches:
                    self.volume_step.emit(1 if notches > 0 else -1)
                    event.accept()
                    return True
            if etype == QEvent.Type.ContextMenu:
                self.context_menu_requested.emit(event.globalPos())
                event.accept()
                return True
        return super().eventFilter(obj, event)
