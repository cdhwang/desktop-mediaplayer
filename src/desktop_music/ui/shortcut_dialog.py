"""Shortcut customization dialog.

Shows each command with its current key sequence. Selecting a row and
pressing a key combination captures a new shortcut; conflicts are rejected
with a status message. A "Restore Defaults" button resets everything.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from desktop_music.core import commands as cmd
from desktop_music.core.shortcuts import ShortcutManager


class ShortcutDialog(QDialog):
    """Lets the user reassign command shortcuts."""

    shortcuts_changed = pyqtSignal()

    def __init__(self, manager: ShortcutManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._manager = manager
        self.setWindowTitle("Keyboard Shortcuts")
        self.resize(420, 480)
        self._build_ui()
        self._reload_table()

    def _build_ui(self) -> None:
        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Action", "Shortcut"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.currentCellChanged.connect(lambda *_: self._sync_editor())

        self._editor = QKeySequenceEdit()
        assign_btn = QPushButton("Assign")
        assign_btn.clicked.connect(self._assign)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._editor.clear)

        edit_row = QHBoxLayout()
        edit_row.addWidget(QLabel("New:"))
        edit_row.addWidget(self._editor, stretch=1)
        edit_row.addWidget(assign_btn)
        edit_row.addWidget(clear_btn)

        self._status = QLabel("")
        self._status.setObjectName("shortcutStatus")

        reset_btn = QPushButton("Restore Defaults")
        reset_btn.clicked.connect(self._reset)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        buttons.addButton(reset_btn, QDialogButtonBox.ButtonRole.ResetRole)

        layout = QVBoxLayout(self)
        layout.addWidget(self._table, stretch=1)
        layout.addLayout(edit_row)
        layout.addWidget(self._status)
        layout.addWidget(buttons)

    def _reload_table(self) -> None:
        mapping = self._manager.mapping
        self._table.setRowCount(len(cmd.COMMANDS))
        for row, command in enumerate(cmd.COMMANDS):
            name_item = QTableWidgetItem(command.label)
            name_item.setData(Qt.ItemDataRole.UserRole, command.id)
            key_item = QTableWidgetItem(mapping.get(command.id, ""))
            self._table.setItem(row, 0, name_item)
            self._table.setItem(row, 1, key_item)

    def _current_command_id(self) -> str | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _sync_editor(self) -> None:
        cid = self._current_command_id()
        if cid is None:
            return
        self._editor.setKeySequence(QKeySequence(self._manager.shortcut_for(cid)))

    def _assign(self) -> None:
        cid = self._current_command_id()
        if cid is None:
            self._status.setText("Select an action first.")
            return
        keyseq = self._editor.keySequence().toString()
        if self._manager.set_shortcut(cid, keyseq):
            self._status.setText(f"Assigned '{keyseq}'.")
            self._reload_table()
            self.shortcuts_changed.emit()
        else:
            conflict = self._manager.conflict_for(keyseq, exclude=cid)
            label = cmd.COMMANDS_BY_ID[conflict].label if conflict else "another action"
            self._status.setText(f"'{keyseq}' already used by {label}.")

    def _reset(self) -> None:
        self._manager.reset_defaults()
        self._reload_table()
        self._sync_editor()
        self._status.setText("Restored default shortcuts.")
        self.shortcuts_changed.emit()

    @property
    def table(self) -> QTableWidget:
        return self._table
