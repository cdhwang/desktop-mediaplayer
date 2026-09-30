"""Equalizer preset selection dialog."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QWidget,
)

from desktop_music.services.equalizer import PRESET_NONE, EqualizerService


class EqualizerDialog(QDialog):
    """Lets the user pick a built-in EQ preset."""

    # emitted whenever the selected preset changes (index, PRESET_NONE for off)
    preset_selected = pyqtSignal(int)

    def __init__(self, service: EqualizerService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self.setWindowTitle("Equalizer")
        self._build_ui()

    def _build_ui(self) -> None:
        self._combo = QComboBox()
        self._combo.addItem("Off", PRESET_NONE)
        for i, name in enumerate(self._service.presets):
            self._combo.addItem(name, i)

        # reflect the currently active preset
        current = self._service.preset_index
        pos = self._combo.findData(current)
        if pos >= 0:
            self._combo.setCurrentIndex(pos)

        self._combo.currentIndexChanged.connect(self._on_changed)

        form = QFormLayout()
        form.addRow("Preset:", self._combo)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        form.addRow(buttons)

        self.setLayout(form)

    def _on_changed(self, _pos: int) -> None:
        index = self._combo.currentData()
        # apply live so the user hears the change immediately
        self._service.apply_preset(index)
        self.preset_selected.emit(index)

    @property
    def combo(self) -> QComboBox:
        return self._combo
