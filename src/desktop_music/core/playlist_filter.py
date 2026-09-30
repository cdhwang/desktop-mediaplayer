"""Filtering proxy for the playlist.

``PlaylistFilterProxy`` matches the query against a track's title, artist,
album, and file name (case-insensitive). It maps rows through to the
source :class:`PlaylistModel` so the view can display a filtered subset
while playback still operates on real source rows.
"""

from __future__ import annotations

import os

from PyQt6.QtCore import QModelIndex, QSortFilterProxyModel

from desktop_music.core.playlist import ArtistRole, PathRole, PlaylistModel, TitleRole


class PlaylistFilterProxy(QSortFilterProxyModel):
    """Case-insensitive multi-field filter over the playlist model."""

    def __init__(self, source: PlaylistModel, parent=None) -> None:
        super().__init__(parent)
        self.setSourceModel(source)
        self._query = ""

    @property
    def source_playlist(self) -> PlaylistModel:
        return self.sourceModel()  # type: ignore[return-value]

    def set_query(self, text: str) -> None:
        self._query = (text or "").strip().lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
        if not self._query:
            return True
        model = self.sourceModel()
        index = model.index(source_row, 0, source_parent)
        haystacks = [
            (model.data(index, TitleRole) or ""),
            (model.data(index, ArtistRole) or ""),
            os.path.basename(model.data(index, PathRole) or ""),
        ]
        # album lives in the track's extra dict; reach through the source track
        track = model.track_at(source_row)
        if track is not None:
            haystacks.append(track.extra.get("album", ""))
        return any(self._query in str(h).lower() for h in haystacks)

    # -- row mapping helpers ----------------------------------------------

    def to_source_row(self, proxy_row: int) -> int:
        idx = self.mapToSource(self.index(proxy_row, 0))
        return idx.row() if idx.isValid() else -1

    def from_source_row(self, source_row: int) -> int:
        model = self.sourceModel()
        idx = self.mapFromSource(model.index(source_row, 0))
        return idx.row() if idx.isValid() else -1
