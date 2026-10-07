"""Auto-scrolling (marquee) text label.

A ``QLabel`` replacement that horizontally scrolls its text when it does not
fit the available width, and renders statically (left-aligned) when it does.
Used for the now-playing track title so a long "Artist - Title" is always
fully readable even in a narrow display area.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFontMetrics, QPainter
from PyQt6.QtWidgets import QWidget

# Pixels scrolled per timer tick and the tick interval (ms).
_STEP_PX = 1
_INTERVAL_MS = 30
# Gap (px) between the end of the text and its wrapped-around repeat.
_GAP_PX = 40
# How long to pause (ms) at the start before scrolling begins / after a wrap.
_PAUSE_MS = 1200


class MarqueeLabel(QWidget):
    """A label that scrolls overflowing text left-to-right automatically."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = text
        self._offset = 0
        self._timer = QTimer(self)
        self._timer.setInterval(_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._paused_ticks = 0
        self.setSizePolicy(
            self.sizePolicy().horizontalPolicy(),
            self.sizePolicy().verticalPolicy(),
        )

    # -- public API --------------------------------------------------------

    def setText(self, text: str) -> None:  # noqa: N802 (Qt-style API)
        if text == self._text:
            return
        self._text = text
        self._offset = 0
        self._paused_ticks = _PAUSE_MS // _INTERVAL_MS
        self._update_scroll_state()
        self.update()

    def text(self) -> str:
        return self._text

    # -- geometry ----------------------------------------------------------

    def _text_width(self) -> int:
        return QFontMetrics(self.font()).horizontalAdvance(self._text)

    def _overflows(self) -> bool:
        return self._text_width() > self.width()

    def _update_scroll_state(self) -> None:
        """Start the timer only when the text overflows and we're visible."""
        if self._text and self._overflows() and self.isVisible():
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
            self._offset = 0

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._update_scroll_state()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        self._update_scroll_state()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().hideEvent(event)
        self._timer.stop()

    def sizeHint(self):  # noqa: N802 (Qt override)
        fm = QFontMetrics(self.font())
        return fm.size(0, self._text or "Mg")

    def minimumSizeHint(self):  # noqa: N802 (Qt override)
        fm = QFontMetrics(self.font())
        hint = fm.size(0, "Mg")
        hint.setWidth(0)  # allow the label to shrink; we scroll to compensate
        return hint

    # -- animation ---------------------------------------------------------

    def _tick(self) -> None:
        if self._paused_ticks > 0:
            self._paused_ticks -= 1
            return
        span = self._text_width() + _GAP_PX
        self._offset += _STEP_PX
        if self._offset >= span:
            # Wrapped a full cycle: reset and pause briefly at the start.
            self._offset = 0
            self._paused_ticks = _PAUSE_MS // _INTERVAL_MS
        self.update()

    # -- painting ----------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setPen(self.palette().text().color())
        fm = QFontMetrics(self.font())
        y = (self.height() + fm.ascent() - fm.descent()) // 2

        if not self._overflows():
            # Fits: draw statically, left-aligned.
            painter.drawText(0, y, self._text)
            painter.end()
            return

        # Overflows: draw the text at -offset, then a wrapped copy after a gap
        # so the scroll reads as a continuous loop.
        span = self._text_width() + _GAP_PX
        x = -self._offset
        painter.drawText(x, y, self._text)
        painter.drawText(x + span, y, self._text)
        painter.end()
