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
from desktop_music.core.playlist import DurationRole, PlaylistModel, TitleRole
from desktop_music.core.playlist_filter import PlaylistFilterProxy
from desktop_music.ui.dnd import extract_paths, has_media_urls


class _TrackDelegate(QStyledItemDelegate):
    """Draws ``NN.  title`` on the left and duration right-aligned."""

    def paint(self, painter, option, index) -> None:
        self.initStyleOption(option, index)
        painter.save()

        if option.state & option.state.__class__.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
            painter.setPen(option.palette.highlightedText().color())
        else:
            painter.setPen(option.palette.text().color())

        rect: QRect = option.rect
        row = index.row() + 1
        title = index.data(Qt.ItemDataRole.DisplayRole) or ""
        duration_ms = index.data(DurationRole) or 0
        duration = format_ms(duration_ms) if duration_ms else ""

        left = rect.adjusted(8, 0, -70, 0)
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
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(max(size.height(), 22))
        return size


class _PlaylistView(QListView):
    """QListView that emits ``delete_pressed`` when Delete/Backspace is hit."""

    delete_pressed = pyqtSignal()

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_pressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class PlaylistPanel(QWidget):
    """Right-hand playlist panel."""

    track_activated = pyqtSignal(int)  # SOURCE row
    add_files_requested = pyqtSignal()
    add_folder_requested = pyqtSignal()
    paths_dropped = pyqtSignal(list)   # media files/folders dropped on the panel

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
            self.paths_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()

    def highlight_current(self, row: int) -> None:
        if row < 0:
            self._view.clearSelection()
            return
        proxy_row = self._proxy.from_source_row(row)
        if proxy_row < 0:
            self._view.clearSelection()
            return
        index = self._proxy.index(proxy_row, 0)
        self._view.setCurrentIndex(index)
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
