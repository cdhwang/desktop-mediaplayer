"""Helpers for moving the top-level window by dragging a child widget.

The central playback area (album art / spectrum / lyrics) acts as a drag
handle for the whole window, mirroring borderless media players. We prefer
the platform's native ``startSystemMove`` (which gives us edge-snapping and
smooth compositor-driven motion); if that is unavailable or fails we fall
back to repositioning the window manually from mouse deltas.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt


class WindowDragMixin:
    """Mixin that lets a widget drag its own top-level window.

    Mix into a ``QWidget`` subclass and call the ``*_drag`` handlers from the
    corresponding Qt mouse event overrides.
    """

    def __init__(self, *args, **kwargs) -> None:  # noqa: D401
        super().__init__(*args, **kwargs)
        self._drag_active = False
        self._drag_offset = None  # window-origin -> cursor offset (fallback path)

    def _window_is_movable(self) -> bool:
        window = self.window()
        if window is None:
            return False
        if window.isFullScreen() or window.isMaximized():
            return False
        return True

    def start_window_drag(self, event) -> bool:
        """Begin a drag. Returns True if the event was consumed."""
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        if not self._window_is_movable():
            return False

        # Prefer the native move: it handles snapping and multi-monitor setups
        # and lets the compositor drive the motion.
        handle = self.window().windowHandle()
        if handle is not None:
            try:
                if handle.startSystemMove():
                    return True
            except (AttributeError, TypeError):
                pass

        # Manual fallback: remember the offset between the window origin and
        # the global cursor so we can keep it constant while dragging.
        self._drag_active = True
        self._drag_offset = (
            event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
        )
        return True

    def continue_window_drag(self, event) -> bool:
        """Move the window during the manual-fallback drag. Returns True if consumed."""
        if not self._drag_active or self._drag_offset is None:
            return False
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return False
        new_pos = event.globalPosition().toPoint() - self._drag_offset
        self.window().move(new_pos)
        return True

    def end_window_drag(self, event) -> bool:
        """End a manual-fallback drag. Returns True if consumed."""
        if self._drag_active:
            self._drag_active = False
            self._drag_offset = None
            return True
        return False
