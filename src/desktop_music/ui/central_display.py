"""Central display stack.

A thin wrapper over ``QStackedWidget`` that switches between named pages:
the album-art view (this task), and later the spectrum visualizer
(Task 10) and video surface (Task 11). Pages register themselves by name
so later tasks can plug in without touching the switching logic.
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QStackedWidget, QWidget

from desktop_music.services.metadata import Metadata
from desktop_music.ui.album_art_view import AlbumArtView
from desktop_music.ui.dnd import extract_paths, has_media_urls
from desktop_music.ui.lyrics_view import LyricsView
from desktop_music.ui.spectrum_widget import SpectrumWidget
from desktop_music.ui.video_surface import VideoSurface

PAGE_ALBUM_ART = "album_art"
PAGE_SPECTRUM = "spectrum"
PAGE_VIDEO = "video"
PAGE_LYRICS = "lyrics"


class CentralDisplay(QStackedWidget):
    """Switchable central content area."""

    # emitted when media files/folders are dropped onto the playback area
    paths_dropped = pyqtSignal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pages: dict[str, QWidget] = {}
        self.setAcceptDrops(True)

        self.album_art = AlbumArtView()
        self.add_page(PAGE_ALBUM_ART, self.album_art)

        self.spectrum = SpectrumWidget()
        self.add_page(PAGE_SPECTRUM, self.spectrum)
        # keep the now-playing mini spectrum in sync with the big one
        self.spectrum.link_mini(self.album_art.mini_spectrum)

        self.lyrics = LyricsView()
        self.add_page(PAGE_LYRICS, self.lyrics)

        self.video = VideoSurface()
        self.add_page(PAGE_VIDEO, self.video)

        self.show_page(PAGE_ALBUM_ART)

    def add_page(self, name: str, widget: QWidget) -> None:
        """Register *widget* under *name* (replacing any existing page)."""
        if name in self._pages:
            self.removeWidget(self._pages[name])
        self._pages[name] = widget
        self.addWidget(widget)

    def show_page(self, name: str) -> None:
        widget = self._pages.get(name)
        if widget is not None:
            self.setCurrentWidget(widget)

    @property
    def current_page(self) -> str:
        current = self.currentWidget()
        for name, widget in self._pages.items():
            if widget is current:
                return name
        return ""

    def has_page(self, name: str) -> bool:
        return name in self._pages

    # -- drag & drop -------------------------------------------------------

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if has_media_urls(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if has_media_urls(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt override)
        paths = extract_paths(event.mimeData())
        if paths:
            self.paths_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()

    # -- convenience -------------------------------------------------------

    def show_metadata(self, meta: Metadata, fallback_title: str = "") -> None:
        self.album_art.show_metadata(meta, fallback_title)

    def clear_metadata(self) -> None:
        self.album_art.clear()

    def set_lyrics(self, text: str) -> None:
        self.lyrics.set_lyrics(text)

    def set_now_playing_time(self, position_ms: int, length_ms: int) -> None:
        self.album_art.set_position(position_ms, length_ms)

    def clear_lyrics(self) -> None:
        self.lyrics.clear()
