"""Playlist side panel (PotPlayer-style).

Layout, top to bottom:
  * a header row ("Playlist")
  * a tab strip ("Default") — a single default tab for now
  * a collapsible search box (toggled by the toolbar search icon)
  * the track list: each row shows ``NN.  Title``  on the left and the
    duration right-aligned, drawn by :class:`_TrackDelegate`
  * a bottom toolbar: ADD / DEL / SORT buttons plus a search toggle

Row indices emitted outward are always *source* rows (filter-independent).
"""

from __future__ import annotations

from PyQt6.QtCore import QModelIndex, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QPushButton,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from desktop_music.core.formatting import format_ms
from desktop_music.core.playlist import (
    DurationRole,
    PlayingRole,
    PlaylistModel,
    TitleRole,
)
from desktop_music.core.playlist_filter import PlaylistFilterProxy
from desktop_music.ui.dnd import extract_paths, has_media_urls

# Cue colors (kept in sync with the dark theme palette).
_PLAYING_ACCENT = QColor("#e0c040")   # now-playing text + marker (yellow)
_FOCUS_BORDER = QColor("#e0c040")     # keyboard-focus outline
_PLAYING_BAR = QColor("#e0c040")      # left edge bar on the playing row


class _TrackDelegate(QStyledItemDelegate):
    """Draws each track row with three *distinct* visual cues:

    * **now playing** — an accent-colored left bar, a ``\u25b6`` marker and
      accent-colored text (driven by the model's :data:`PlayingRole`).
    * **selected** — the palette highlight background (user selection).
    * **keyboard focus** — a dashed accent outline around the current item.

    These are independent: a row can be selected without being the playing
    row, focused without being selected, and so on.
    """

    _MARKER_W = 16  # px reserved for the ``\u25b6`` now-playing marker

    def paint(self, painter, option, index) -> None:
        self.initStyleOption(option, index)
        painter.save()

        state = option.state
        is_selected = bool(state & state.__class__.State_Selected)
        is_focused = bool(state & state.__class__.State_HasFocus)
        is_playing = bool(index.data(PlayingRole))

        # 1) Background: selection takes the highlight fill.
        if is_selected:
            painter.fillRect(option.rect, option.palette.highlight())

        rect: QRect = option.rect

        # 2) Now-playing cue: left accent bar + marker + accent text color.
        if is_playing:
            bar = QRect(rect.left(), rect.top(), 3, rect.height())
            painter.fillRect(bar, _PLAYING_BAR)
            marker_rect = rect.adjusted(6, 0, 0, 0)
            painter.setPen(_PLAYING_ACCENT)
            painter.drawText(
                marker_rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                "\u25b6",
            )

        # 3) Text color: playing -> accent, selected -> highlighted text,
        #    otherwise normal text.
        if is_playing:
            painter.setPen(_PLAYING_ACCENT)
        elif is_selected:
            painter.setPen(option.palette.highlightedText().color())
        else:
            painter.setPen(option.palette.text().color())

        row = index.row() + 1
        title = index.data(Qt.ItemDataRole.DisplayRole) or ""
        duration_ms = index.data(DurationRole) or 0
        duration = format_ms(duration_ms) if duration_ms else ""

        # Reserve space for the marker on the playing row so text does not
        # shift relative to other rows.
        left_pad = 8 + self._MARKER_W if is_playing else 8
        left = rect.adjusted(left_pad, 0, -70, 0)
        painter.drawText(
            left,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            f"{row:02d}.  {title}",
        )
        if duration:
            right = rect.adjusted(0, 0, -8, 0)
            painter.drawText(
                right,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                duration,
            )

        # 4) Keyboard-focus cue: dashed accent outline, drawn last so it sits
        #    on top of any background/selection fill.
        if is_focused:
            pen = QPen(_FOCUS_BORDER)
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setWidth(1)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(0, 0, -1, -1))

        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(max(size.height(), 22))
        return size


class _PlaylistView(QListView):
    """QListView with Delete-to-remove and drag-to-reorder support.

    * emits ``delete_pressed`` when Delete/Backspace is hit.
    * emits ``reorder_requested(src_source_row, dst_source_row)`` when the
      user drags a row to a new position. Rows are *source* rows (filter
      independent). Internal reordering is disabled while a search filter is
      active, because a positional move within a filtered subset would be
      ambiguous against the full list.
    """

    delete_pressed = pyqtSignal()
    reorder_requested = pyqtSignal(int, int)  # (src source row, dst source row)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_pressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def _reorder_enabled(self) -> bool:
        """True when the proxy shows the full, unfiltered list 1:1."""
        proxy = self.model()
        source = proxy.sourceModel() if proxy is not None else None
        if proxy is None or source is None:
            return False
        return proxy.rowCount() == source.rowCount()

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.source() is self and self._reorder_enabled():
            event.acceptProposedAction()
        else:
            # Let an external file drop bubble up to the panel.
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.source() is self and self._reorder_enabled():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.source() is not self or not self._reorder_enabled():
            event.ignore()
            return
        selected = self.selectionModel().selectedRows()
        src_proxy = selected[0].row() if selected else self.currentIndex().row()
        if src_proxy < 0:
            event.ignore()
            return

        pos = event.position().toPoint()
        index = self.indexAt(pos)
        if index.isValid():
            dst_proxy = index.row()
            rect = self.visualRect(index)
            if pos.y() > rect.center().y():
                dst_proxy += 1
        else:
            dst_proxy = self.model().rowCount()  # dropped past the last row

        # Translate "insert before dst_proxy" into a final resting index.
        if dst_proxy > src_proxy:
            dst_proxy -= 1
        dst_proxy = max(0, min(dst_proxy, self.model().rowCount() - 1))
        if dst_proxy == src_proxy:
            event.ignore()
            return

        proxy = self.model()
        src = proxy.mapToSource(proxy.index(src_proxy, 0)).row()
        dst = proxy.mapToSource(proxy.index(dst_proxy, 0)).row()
        if src < 0 or dst < 0:
            event.ignore()
            return
        self.reorder_requested.emit(src, dst)
        event.acceptProposedAction()


class PlaylistPanel(QWidget):
    """Right-hand playlist panel."""

    track_activated = pyqtSignal(int)  # SOURCE row
    add_files_requested = pyqtSignal()
    add_folder_requested = pyqtSignal()
    paths_dropped = pyqtSignal(list, int)   # (media files/folders, insert source row; -1 = append)

    def __init__(self, model: PlaylistModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = model
        self._proxy = PlaylistFilterProxy(model, self)
        self.setAcceptDrops(True)
        self._build_ui()

    def _build_ui(self) -> None:
        self.setMinimumWidth(260)
        self.setObjectName("playlistPanel")

        header = QLabel("Playlist")
        header.setObjectName("panelHeader")

        # tab strip (single default tab for now)
        self._tab = QLabel("Default")
        self._tab.setObjectName("playlistTab")
        tab_row = QHBoxLayout()
        tab_row.setContentsMargins(0, 0, 0, 0)
        tab_row.addWidget(self._tab)
        tab_row.addStretch(1)

        # collapsible search box
        self._search = QLineEdit()
        self._search.setObjectName("searchBox")
        self._search.setPlaceholderText("Search title / artist / album\u2026")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._proxy.set_query)
        self._search.hide()

        self._view = _PlaylistView()
        self._view.setObjectName("playlistView")
        self._view.setModel(self._proxy)
        self._view.setItemDelegate(_TrackDelegate(self._view))
        self._view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._view.setUniformItemSizes(True)
        self._view.doubleClicked.connect(
            lambda index: self.track_activated.emit(self._proxy.to_source_row(index.row()))
        )
        self._view.delete_pressed.connect(self._remove_selected)
        self._view.reorder_requested.connect(self._reorder)

        # bottom toolbar: ADD / DEL / SORT + search toggle
        self._add_btn = self._tool_btn("ADD", self.add_files_requested)
        self._del_btn = self._tool_btn("DEL", self._remove_selected)
        self._sort_btn = self._tool_btn("SORT", self._sort)
        self._search_btn = self._tool_btn("\U0001f50d", self._toggle_search)
        self._search_btn.setFixedWidth(34)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(4)
        toolbar.addWidget(self._add_btn)
        toolbar.addWidget(self._del_btn)
        toolbar.addWidget(self._sort_btn)
        toolbar.addStretch(1)
        toolbar.addWidget(self._search_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        layout.addWidget(header)
        layout.addLayout(tab_row)
        layout.addWidget(self._search)
        layout.addWidget(self._view, stretch=1)
        layout.addLayout(toolbar)

    def _tool_btn(self, text: str, slot) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("playlistToolButton")
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.clicked.connect(slot)
        return btn

    @property
    def view(self) -> _PlaylistView:
        return self._view

    @property
    def proxy(self) -> PlaylistFilterProxy:
        return self._proxy

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
            self.paths_dropped.emit(paths, self._drop_source_row(event))
            event.acceptProposedAction()
        else:
            event.ignore()

    def _drop_source_row(self, event) -> int:
        """Source row at which dropped items should be inserted.

        Maps the drop position to a view row, then to a source row. Dropping
        on the lower half of a row inserts *after* it. Returns ``-1`` to mean
        "append" — used when the drop lands past the last item or while a
        search filter is active (positional insert is ambiguous when the
        visible list is a filtered subset).
        """
        if self._model.rowCount() == 0:
            return -1  # empty list -> append
        if self._proxy.rowCount() != self._model.rowCount():
            return -1  # a filter is active -> fall back to append
        pos = event.position().toPoint()
        index = self._view.indexAt(pos)
        if not index.isValid():
            return -1  # dropped on empty space -> append
        proxy_row = index.row()
        rect = self._view.visualRect(index)
        if pos.y() > rect.center().y():
            proxy_row += 1  # lower half -> insert after this row
        src = self._proxy.to_source_row(proxy_row)
        if src < 0:
            # proxy_row is past the last mapped row (append position)
            return self._model.rowCount()
        return src

    def highlight_current(self, row: int) -> None:
        """React to the now-playing row changing.

        The "now playing" cue is painted by the delegate from the model's
        :data:`PlayingRole`, so this does **not** touch the view's selection
        or current (focus) index — those stay under the user's control. We
        only scroll the playing row into view for convenience.
        """
        if row < 0:
            return
        proxy_row = self._proxy.from_source_row(row)
        if proxy_row < 0:
            return
        index = self._proxy.index(proxy_row, 0)
        self._view.scrollTo(index)

    # -- toolbar actions ---------------------------------------------------

    def _toggle_search(self) -> None:
        if self._search.isHidden():
            self._search.show()
            self._search.setFocus()
        else:
            self._search.hide()
            self._search.clear()

    def _sort(self) -> None:
        """Sort tracks by display title (source order)."""
        model = self._model
        model._tracks.sort(key=lambda t: t.display_title.lower())
        model.layoutChanged.emit()

    def _reorder(self, src: int, dst: int) -> None:
        """Move a track from source row ``src`` to ``dst`` (final position)."""
        self._model.move_row(src, dst)

    def _remove_selected(self) -> None:
        source_rows = sorted(
            (self._proxy.to_source_row(i.row()) for i in self._view.selectionModel().selectedRows()),
            reverse=True,
        )
        source_rows = [r for r in source_rows if r >= 0]
        if not source_rows:
            idx = self._view.currentIndex()
            if idx.isValid():
                src = self._proxy.to_source_row(idx.row())
                if src >= 0:
                    source_rows = [src]
        for row in source_rows:
            self._model.remove_row(row)
