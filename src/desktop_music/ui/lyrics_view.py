"""Lyrics display: a scrollable, read-only text view."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QTextEdit, QVBoxLayout, QWidget


class LyricsView(QWidget):
    """Shows plain-text lyrics for the current track."""

    _PLACEHOLDER = "No lyrics available."

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()
        self.clear()

    def _build_ui(self) -> None:
        header = QLabel("Lyrics")
        header.setObjectName("panelHeader")

        self._text = QTextEdit()
        self._text.setObjectName("lyricsText")
        self._text.setReadOnly(True)
        self._text.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(header)
        layout.addWidget(self._text, stretch=1)

    def clear(self) -> None:
        self._text.setPlainText(self._PLACEHOLDER)

    def set_lyrics(self, text: str) -> None:
        self._text.setPlainText(text if text else self._PLACEHOLDER)

    @property
    def has_lyrics(self) -> bool:
        return self._text.toPlainText() not in ("", self._PLACEHOLDER)
