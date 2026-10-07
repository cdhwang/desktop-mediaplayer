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
# True when this row is the track currently loaded/playing. Distinct from
# Qt's selection/current (focus) state so the delegate can draw a separate cue.
PlayingRole = Qt.ItemDataRole.UserRole + 5


@dataclass
class Track:
    """A single playlist entry."""

    path: str
    title: str = ""
    artist: str = ""
    duration_ms: int = 0
    # Cue-sheet track bounds within ``path`` (ms). ``end_ms == 0`` means
    # "until the end of the file". When both are 0 the whole file plays.
    start_ms: int = 0
    end_ms: int = 0
    # extra metadata slots filled by later tasks (album, art, etc.)
    extra: dict = field(default_factory=dict)

    @property
    def is_cue_track(self) -> bool:
        """True when this entry is a slice of a larger backing file."""
        return self.start_ms > 0 or self.end_ms > 0

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
        if role == Qt.ItemDataRole.ToolTipRole:
            # Full, untruncated info for the hover tooltip: the display title
            # plus the source path so long names are always readable.
            if track.path and track.path != track.display_title:
                return f"{track.display_title}\n{track.path}"
            return track.display_title
        if role == PathRole:
            return track.path
        if role == TitleRole:
            return track.title
        if role == ArtistRole:
            return track.artist
        if role == DurationRole:
            return track.duration_ms
        if role == PlayingRole:
            return index.row() == self._current
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:  # noqa: N802
        """Expose drag/drop flags so the view can start reorder drags.

        Valid rows are draggable; invalid (empty-space) indexes are drop
        targets so an item can be dropped at the end of the list.
        """
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.isValid():
            return base | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled
        return base | Qt.ItemFlag.ItemIsDropEnabled


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
            old = self._current
            self._current = new
            # Repaint the rows whose "now playing" cue changed so the delegate
            # updates without touching selection/focus state.
            for r in (old, new):
                if 0 <= r < len(self._tracks):
                    idx = self.index(r, 0)
                    self.dataChanged.emit(idx, idx, [PlayingRole])
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
        """Add multiple files and/or directories (recursively) at the end.

        Returns the number of tracks added.
        """
        return self.insert_paths(len(self._tracks), paths)

    def insert_paths(self, row: int, paths: list[str]) -> int:
        """Insert files and/or directories (recursively) *before* ``row``.

        ``row`` is a source row in ``[0, rowCount]``; it is clamped to that
        range (``rowCount`` appends at the end). Returns the number of tracks
        inserted. The current (now-playing) index is shifted so it keeps
        pointing at the same track.
        """
        collected = self._collect_tracks(paths)
        if not collected:
            return 0
        row = max(0, min(row, len(self._tracks)))
        count = len(collected)
        self.beginInsertRows(QModelIndex(), row, row + count - 1)
        self._tracks[row:row] = collected
        self.endInsertRows()
        if self._current == -1:
            self.set_current(0)
        elif row <= self._current:
            # tracks were inserted at or before the playing row: keep the
            # same track current by shifting the cursor.
            self._current += count
            self.current_changed.emit(self._current)
        return count

    @staticmethod
    def _collect_tracks(paths: list[str]) -> list["Track"]:
        """Expand *paths* into :class:`Track` objects.

        * directories are scanned recursively for supported media files;
        * ``.cue`` sheets given directly are expanded into one track per
          cue ``TRACK`` (each a slice of the backing file); the cue file
          itself is never added;
        * ``.cue`` files found while scanning a directory are ignored
          (directory scans only collect supported media extensions).
        """
        from desktop_music.services.cue import is_cue, parse_cue_tracks

        collected: list[Track] = []
        for p in paths:
            if os.path.isdir(p):
                collected.extend(Track(path=f) for f in _scan_dir(p))
            elif is_cue(p):
                for ct in parse_cue_tracks(p):
                    duration = (
                        ct.end_ms - ct.start_ms if ct.end_ms > ct.start_ms else 0
                    )
                    collected.append(
                        Track(
                            path=ct.path,
                            title=ct.title,
                            artist=ct.artist,
                            start_ms=ct.start_ms,
                            end_ms=ct.end_ms,
                            duration_ms=duration,
                        )
                    )
            elif is_media(p):
                collected.append(Track(path=p))
        return collected

    @staticmethod
    def _collect_paths(paths: list[str]) -> list[str]:
        """Backward-compatible path-only collector (no cue track slicing).

        ``.cue`` sheets given directly are expanded into the media files they
        reference (the cue file itself is never added). ``.cue`` files found
        while scanning a directory are ignored — directory scans only collect
        supported media extensions, which excludes ``.cue``.
        """
        from desktop_music.services.cue import is_cue, parse_cue_files

        collected: list[str] = []
        for p in paths:
            if os.path.isdir(p):
                collected.extend(_scan_dir(p))
            elif is_cue(p):
                collected.extend(parse_cue_files(p))
            elif is_media(p):
                collected.append(p)
        return collected

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

    def move_row(self, src: int, dst: int) -> bool:
        """Move the track at ``src`` so it ends up at index ``dst``.

        ``dst`` is interpreted as the final resting position in the list
        (0..rowCount-1). The now-playing cursor is updated to keep pointing
        at the same track. Returns True if a move happened.
        """
        n = len(self._tracks)
        if n < 2:
            return False
        if not (0 <= src < n):
            return False
        dst = max(0, min(dst, n - 1))
        if src == dst:
            return False

        # beginMoveRows expects the destination row in the *source* coordinate
        # system (where the item would be inserted before). When moving down,
        # that insertion point is one past the target index.
        dest_for_qt = dst + 1 if dst > src else dst
        if not self.beginMoveRows(QModelIndex(), src, src, QModelIndex(), dest_for_qt):
            return False
        track = self._tracks.pop(src)
        self._tracks.insert(dst, track)
        self.endMoveRows()

        # Update the current cursor so it follows the same track.
        cur = self._current
        if cur == src:
            cur = dst
        elif src < cur <= dst:
            cur -= 1
        elif dst <= cur < src:
            cur += 1
        if cur != self._current:
            self._current = cur
            self.current_changed.emit(self._current)
        return True

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
        is_cue = track.is_cue_track
        # Cue tracks carry their own per-track title/artist and a segment
        # duration derived from the sheet. Don't let whole-file metadata
        # (e.g. the full .ape length or album-level tags) overwrite them.
        if title and not (is_cue and track.title):
            track.title = title
        if artist and not (is_cue and track.artist):
            track.artist = artist
        if album:
            track.extra["album"] = album
        if duration_ms and not is_cue:
            track.duration_ms = duration_ms
        elif duration_ms and is_cue and track.end_ms == 0 and track.duration_ms == 0:
            # Last cue track of a file (plays to EOF): derive its length from
            # the full-file duration minus this track's start offset.
            remaining = duration_ms - track.start_ms
            if remaining > 0:
                track.duration_ms = remaining
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
