"""Album-art + now-playing view for audio tracks.

Mirrors PotPlayer's audio view: a large album-art area on top, and a
bottom "now-playing" overlay row showing the big elapsed/total time, the
track title, the technical info line (e.g. ``MP3 320kbps 44.1khz``), and a
small mini-spectrum on the right.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QGridLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from desktop_music.core.formatting import format_ms
from desktop_music.services.metadata import Metadata
from desktop_music.ui.spectrum_widget import MiniSpectrum


class AlbumArtView(QWidget):
    """Cover art with a PotPlayer-style now-playing overlay beneath it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()
        self.clear()

    def _build_ui(self) -> None:
        self._art = QLabel()
        self._art.setObjectName("albumArt")
        self._art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._art.setMinimumSize(200, 200)

        # ---- now-playing overlay -------------------------------------
        self._elapsed = QLabel("00:00")
        self._elapsed.setObjectName("bigTime")
        self._total = QLabel("00:00")
        self._total.setObjectName("bigTimeTotal")

        self._title = QLabel("")
        self._title.setObjectName("nowPlayingTitle")
        self._title.setWordWrap(False)
        self._tech = QLabel("")
        self._tech.setObjectName("nowPlayingTech")

        self._mini = MiniSpectrum()

        overlay = QGridLayout()
        overlay.setContentsMargins(16, 8, 16, 8)
        overlay.setHorizontalSpacing(12)
        # column 0: stacked big time (elapsed over total)
        time_box = QVBoxLayout()
        time_box.setSpacing(0)
        time_box.addWidget(self._elapsed)
        time_box.addWidget(self._total)
        overlay.addLayout(time_box, 0, 0, 2, 1)
        # column 1: title + tech info
        overlay.addWidget(self._title, 0, 1)
        overlay.addWidget(self._tech, 1, 1)
        overlay.setColumnStretch(1, 1)
        # column 2: mini spectrum
        overlay.addWidget(self._mini, 0, 2, 2, 1)

        overlay_widget = QWidget()
        overlay_widget.setObjectName("nowPlayingBar")
        overlay_widget.setLayout(overlay)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._art, stretch=1)
        layout.addWidget(overlay_widget)

    # -- public API --------------------------------------------------------

    def clear(self) -> None:
        self._art.setPixmap(QPixmap())
        self._art.setText("\u266a")
        self._title.setText("")
        self._tech.setText("")
        self._elapsed.setText("00:00")
        self._total.setText("00:00")

    def show_metadata(self, meta: Metadata, fallback_title: str = "") -> None:
        """Display *meta*, using *fallback_title* when the title tag is empty."""
        title = meta.title or fallback_title
        if meta.artist:
            title = f"{meta.artist} - {title}"
        self._title.setText(title)
        self._tech.setText(meta.tech_info)

        if meta.cover_art:
            pixmap = QPixmap()
            if pixmap.loadFromData(meta.cover_art):
                self._set_art(pixmap)
                return
        self._art.setPixmap(QPixmap())
        self._art.setText("\u266a")

    def set_position(self, position_ms: int, length_ms: int) -> None:
        """Update the big elapsed / total time labels."""
        self._elapsed.setText(format_ms(position_ms))
        self._total.setText(format_ms(length_ms))

    @property
    def mini_spectrum(self) -> MiniSpectrum:
        return self._mini

    def _set_art(self, pixmap: QPixmap) -> None:
        self._art.setText("")
        scaled = pixmap.scaled(
            self._art.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._art.setPixmap(scaled)

    @property
    def has_art(self) -> bool:
        pm = self._art.pixmap()
        return pm is not None and not pm.isNull()
