"""Playlist model.

``PlaylistModel`` is a ``QAbstractListModel`` holding an ordered list of
:class:`Track` items. It owns the notion of a "current" index and exposes
``next_index``/``previous_index`` helpers. Shuffle and repeat behaviour is
introduced in Task 5 via :class:`~desktop_music.core.playmode.PlayMode`;
this model keeps a pluggable hook (``_advance_policy``) so that layering is
non-invasive. Metadata enrichment (title/artist) arrives in Task 6.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from PyQt6.QtCore import QAbstractListModel, QModelIndex, Qt, pyqtSignal

from desktop_music.constants import MEDIA_EXTENSIONS, is_media

# Custom item data roles.
PathRole = Qt.ItemDataRole.UserRole + 1
TitleRole = Qt.ItemDataRole.UserRole + 2
ArtistRole = Qt.ItemDataRole.UserRole + 3
DurationRole = Qt.ItemDataRole.UserRole + 4


@dataclass
class Track:
    """A single playlist entry."""

    path: str
    title: str = ""
    artist: str = ""
    duration_ms: int = 0
    # extra metadata slots filled by later tasks (album, art, etc.)
    extra: dict = field(default_factory=dict)

    @property
    def display_title(self) -> str:
        """Best-effort display name."""
        if self.title:
            if self.artist:
                return f"{self.artist} - {self.title}"
            return self.title
        return os.path.basename(self.path)


class PlaylistModel(QAbstractListModel):
    """Ordered collection of tracks with a current-index cursor."""

    current_changed = pyqtSignal(int)  # emits the new current row (-1 if none)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._tracks: list[Track] = []
        self._current: int = -1

    # -- Qt model API ------------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._tracks)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._tracks)):
            return None
        track = self._tracks[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return track.display_title
        if role == PathRole:
            return track.path
        if role == TitleRole:
            return track.title
        if role == ArtistRole:
            return track.artist
        if role == DurationRole:
            return track.duration_ms
        return None

    # -- track access ------------------------------------------------------

    @property
    def tracks(self) -> list[Track]:
        return self._tracks

    def track_at(self, row: int) -> Optional[Track]:
        if 0 <= row < len(self._tracks):
            return self._tracks[row]
        return None

    @property
    def current_index(self) -> int:
        return self._current

    def current_track(self) -> Optional[Track]:
        return self.track_at(self._current)

    def set_current(self, row: int) -> None:
        """Set the current row; clamps to valid range or -1 when empty."""
        if not self._tracks:
            new = -1
        else:
            new = max(0, min(row, len(self._tracks) - 1))
        if new != self._current:
            self._current = new
            self.current_changed.emit(self._current)

    # -- mutation ----------------------------------------------------------

    def add_path(self, path: str) -> int:
        """Add a single media file. Returns the number of tracks added."""
        if not is_media(path):
            return 0
        self.beginInsertRows(QModelIndex(), len(self._tracks), len(self._tracks))
        self._tracks.append(Track(path=path))
        self.endInsertRows()
        if self._current == -1:
            self.set_current(0)
        return 1

    def add_paths(self, paths: list[str]) -> int:
        """Add multiple files and/or directories (recursively). Returns count."""
        collected: list[str] = []
        for p in paths:
            if os.path.isdir(p):
                collected.extend(_scan_dir(p))
            elif is_media(p):
                collected.append(p)
        if not collected:
            return 0
        start = len(self._tracks)
        self.beginInsertRows(QModelIndex(), start, start + len(collected) - 1)
        self._tracks.extend(Track(path=p) for p in collected)
        self.endInsertRows()
        if self._current == -1:
            self.set_current(0)
        return len(collected)

    def remove_row(self, row: int) -> None:
        if not (0 <= row < len(self._tracks)):
            return
        self.beginRemoveRows(QModelIndex(), row, row)
        del self._tracks[row]
        self.endRemoveRows()
        if not self._tracks:
            self.set_current(-1)
        elif row < self._current:
            self._current -= 1
            self.current_changed.emit(self._current)
        elif row == self._current:
            # keep pointing at the same position (now the next track)
            self._current = min(self._current, len(self._tracks) - 1)
            self.current_changed.emit(self._current)

    def clear(self) -> None:
        self.beginResetModel()
        self._tracks.clear()
        self._current = -1
        self.endResetModel()
        self.current_changed.emit(-1)

    def update_track_metadata(
        self,
        row: int,
        *,
        title: str = "",
        artist: str = "",
        album: str = "",
        duration_ms: int = 0,
    ) -> None:
        """Enrich a track with extracted metadata and notify views."""
        track = self.track_at(row)
        if track is None:
            return
        if title:
            track.title = title
        if artist:
            track.artist = artist
        if album:
            track.extra["album"] = album
        if duration_ms:
            track.duration_ms = duration_ms
        index = self.index(row, 0)
        self.dataChanged.emit(index, index)

    # -- persistence -------------------------------------------------------

    def to_state(self) -> dict:
        """Serialize the playlist to a JSON-friendly dict."""
        return {
            "paths": [t.path for t in self._tracks],
            "current": self._current,
        }

    def load_state(self, state: dict) -> None:
        """Restore the playlist from a dict produced by :meth:`to_state`.

        Missing files are skipped so a moved/deleted track does not break
        startup. The saved current index is clamped to the restored list.
        """
        paths = state.get("paths", []) if isinstance(state, dict) else []
        current = state.get("current", -1) if isinstance(state, dict) else -1
        valid = [p for p in paths if isinstance(p, str) and os.path.exists(p)]
        self.beginResetModel()
        self._tracks = [Track(path=p) for p in valid]
        self._current = -1
        self.endResetModel()
        if self._tracks:
            self.set_current(current if 0 <= current < len(self._tracks) else 0)

    # -- navigation --------------------------------------------------------

    def next_index(self, wrap: bool = True) -> int:
        """Return the row that follows the current one (-1 if none)."""
        if not self._tracks:
            return -1
        nxt = self._current + 1
        if nxt >= len(self._tracks):
            return 0 if wrap else -1
        return nxt

    def previous_index(self, wrap: bool = True) -> int:
        """Return the row preceding the current one (-1 if none)."""
        if not self._tracks:
            return -1
        prev = self._current - 1
        if prev < 0:
            return len(self._tracks) - 1 if wrap else -1
        return prev


def _scan_dir(directory: str) -> list[str]:
    """Recursively collect supported media files under *directory*, sorted."""
    found: list[str] = []
    for root, _dirs, files in os.walk(directory):
        for name in files:
            if os.path.splitext(name)[1].lower() in MEDIA_EXTENSIONS:
                found.append(os.path.join(root, name))
    found.sort()
    return found


def scan_dir_flat(directory: str) -> list[str]:
    """Collect supported media files directly in *directory* (non-recursive).

    Returns absolute paths, sorted.
    """
    found: list[str] = []
    try:
        entries = os.listdir(directory)
    except OSError:
        return found
    for name in entries:
        full = os.path.abspath(os.path.join(directory, name))
        if os.path.isfile(full) and os.path.splitext(name)[1].lower() in MEDIA_EXTENSIONS:
            found.append(full)
    found.sort()
    return found
