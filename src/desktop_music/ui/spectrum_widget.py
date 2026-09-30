"""Spectrum visualizer widget.

Renders animated frequency bars synchronized to the current playback
position. Analysis runs on a background thread (``_AnalyzerThread``) so
loading a file never blocks the UI; until analysis finishes the bars stay
flat. A repaint timer drives the ~30fps animation.
"""

from __future__ import annotations

import numpy as np
from PyQt6.QtCore import QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter
from PyQt6.QtWidgets import QWidget

from desktop_music.services.spectrum import NUM_BANDS, SpectrumData, analyze_file

_FPS = 30
_SMOOTHING = 0.35  # exponential smoothing factor for bar heights


class MiniSpectrum(QWidget):
    """A small, compact spectrum bar strip for the now-playing overlay.

    It does not run its own analysis; instead it is fed level arrays by the
    main :class:`SpectrumWidget` so both stay in sync cheaply.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(90, 34)
        self._levels = np.zeros(NUM_BANDS, dtype=np.float32)

    def set_levels(self, levels: np.ndarray) -> None:
        self._levels = levels
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        w, h = self.width(), self.height()
        n = len(self._levels)
        if n == 0 or w <= 0 or h <= 0:
            return
        gap = 1
        bar_w = max(1, (w - gap * (n + 1)) / n)
        x = gap
        for level in self._levels:
            bar_h = max(1, float(level) * (h - 2))
            painter.fillRect(
                int(x), int(h - bar_h), int(bar_w), int(bar_h), QColor(150, 150, 160)
            )
            x += bar_w + gap


class _AnalyzerThread(QThread):
    """Runs offline analysis for one file off the UI thread."""

    ready = pyqtSignal(str, object)  # (path, SpectrumData)

    def __init__(self, path: str, parent=None) -> None:
        super().__init__(parent)
        self._path = path

    def run(self) -> None:
        data = analyze_file(self._path)
        self.ready.emit(self._path, data)


class SpectrumWidget(QWidget):
    """Animated frequency-bar visualizer."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(160)
        self._data: SpectrumData | None = None
        self._current_path = ""
        self._position_ms = 0
        self._levels = np.zeros(NUM_BANDS, dtype=np.float32)
        self._thread: _AnalyzerThread | None = None
        self._mini: MiniSpectrum | None = None

        self._timer = QTimer(self)
        self._timer.setInterval(1000 // _FPS)
        self._timer.timeout.connect(self._tick)

    def link_mini(self, mini: "MiniSpectrum") -> None:
        """Attach a MiniSpectrum that mirrors this widget's levels."""
        self._mini = mini

    # -- public API --------------------------------------------------------

    def analyze(self, path: str) -> None:
        """Kick off background analysis for *path*."""
        self._current_path = path
        self._data = None
        self._levels[:] = 0.0
        self._start_thread(path)

    def set_position(self, ms: int) -> None:
        self._position_ms = ms

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    @property
    def has_data(self) -> bool:
        return self._data is not None and self._data.num_frames > 0

    # -- analysis lifecycle -----------------------------------------------

    def _start_thread(self, path: str) -> None:
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(100)
        self._thread = _AnalyzerThread(path, self)
        self._thread.ready.connect(self._on_ready)
        self._thread.start()

    def _on_ready(self, path: str, data: SpectrumData) -> None:
        # ignore results for a file we're no longer playing
        if path == self._current_path:
            self._data = data

    def _stop_thread(self) -> None:
        """Stop and wait for any running analyzer thread (teardown-safe)."""
        if self._thread is not None:
            if self._thread.isRunning():
                self._thread.quit()
                self._thread.wait(2000)
            self._thread = None

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._timer.stop()
        self._stop_thread()
        super().closeEvent(event)

    # -- animation ---------------------------------------------------------

    def _tick(self) -> None:
        target = (
            self._data.frame_at_ms(self._position_ms)
            if self.has_data
            else np.zeros(NUM_BANDS, dtype=np.float32)
        )
        # exponential smoothing for a fluid look
        self._levels += (target - self._levels) * (1.0 - _SMOOTHING)
        if self._mini is not None:
            self._mini.set_levels(self._levels)
        self.update()

    # -- painting ----------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(18, 18, 22))

        w = self.width()
        h = self.height()
        n = len(self._levels)
        if n == 0 or w <= 0 or h <= 0:
            return

        gap = 2
        bar_w = max(1, (w - gap * (n + 1)) / n)
        gradient = QLinearGradient(0, h, 0, 0)
        gradient.setColorAt(0.0, QColor(60, 120, 220))
        gradient.setColorAt(1.0, QColor(120, 220, 255))

        x = gap
        for level in self._levels:
            bar_h = max(1, float(level) * (h - 4))
            painter.fillRect(
                int(x), int(h - bar_h), int(bar_w), int(bar_h), gradient
            )
            x += bar_w + gap
