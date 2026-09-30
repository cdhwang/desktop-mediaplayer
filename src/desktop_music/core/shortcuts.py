"""Customizable keyboard shortcut system.

``ShortcutManager`` owns the mapping of command id -> key sequence, binds
``QShortcut`` objects to a host widget (window-scoped per requirement 11=a),
detects conflicts, supports restoring defaults, and (de)serializes the
mapping for :class:`SettingsStore`.
"""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QObject, Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QWidget

from desktop_music.core import commands as cmd


class ShortcutManager(QObject):
    """Binds named commands to key sequences on a host widget."""

    def __init__(self, host: QWidget, dispatch: Callable[[str], None]) -> None:
        super().__init__(host)
        self._host = host
        self._dispatch = dispatch
        self._mapping: dict[str, str] = cmd.default_shortcuts()
        self._shortcuts: dict[str, QShortcut] = {}

    @property
    def mapping(self) -> dict[str, str]:
        return dict(self._mapping)

    def shortcut_for(self, command_id: str) -> str:
        return self._mapping.get(command_id, "")

    # -- binding -----------------------------------------------------------

    def rebind_all(self) -> None:
        """(Re)create all QShortcut objects from the current mapping."""
        for sc in self._shortcuts.values():
            sc.setParent(None)
        self._shortcuts.clear()

        for command_id, keyseq in self._mapping.items():
            if not keyseq:
                continue
            shortcut = QShortcut(QKeySequence(keyseq), self._host)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(
                lambda cid=command_id: self._dispatch(cid)
            )
            self._shortcuts[command_id] = shortcut

    # -- customization -----------------------------------------------------

    def conflict_for(self, keyseq: str, exclude: str | None = None) -> str | None:
        """Return the command id already using *keyseq*, or None.

        Comparison is done via normalized :class:`QKeySequence` strings so
        equivalent spellings (e.g. "ctrl+s" vs "Ctrl+S") are detected.
        """
        if not keyseq:
            return None
        target = QKeySequence(keyseq).toString()
        for cid, existing in self._mapping.items():
            if cid == exclude or not existing:
                continue
            if QKeySequence(existing).toString() == target:
                return cid
        return None

    def set_shortcut(self, command_id: str, keyseq: str) -> bool:
        """Assign *keyseq* to *command_id*. Returns False on conflict."""
        if command_id not in self._mapping:
            return False
        conflict = self.conflict_for(keyseq, exclude=command_id)
        if conflict is not None:
            return False
        self._mapping[command_id] = keyseq
        self.rebind_all()
        return True

    def reset_defaults(self) -> None:
        self._mapping = cmd.default_shortcuts()
        self.rebind_all()

    # -- persistence -------------------------------------------------------

    def to_state(self) -> dict:
        return dict(self._mapping)

    def load_state(self, state: dict) -> None:
        if not isinstance(state, dict):
            return
        # start from defaults so newly added commands get their default key
        merged = cmd.default_shortcuts()
        for cid, keyseq in state.items():
            if cid in merged and isinstance(keyseq, str):
                merged[cid] = keyseq
        self._mapping = merged
        self.rebind_all()
