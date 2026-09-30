"""Tests for the equalizer service and dialog (Task 8)."""

from __future__ import annotations

from unittest.mock import MagicMock

from desktop_music.services.equalizer import (
    PRESET_NONE,
    EqualizerService,
    preset_names,
)
from desktop_music.ui.equalizer_dialog import EqualizerDialog


def test_preset_names_nonempty() -> None:
    names = preset_names()
    assert len(names) > 0
    assert "Flat" in names


def _service_with_mock_player():
    backend = MagicMock()
    player = MagicMock()
    player.set_equalizer.return_value = 0  # libVLC success
    backend.player = player
    return EqualizerService(backend), player


def test_apply_preset_calls_set_equalizer() -> None:
    service, player = _service_with_mock_player()
    rock = service.presets.index("Rock")
    assert service.apply_preset(rock) is True
    assert service.preset_index == rock
    player.set_equalizer.assert_called_once()


def test_apply_preset_off_passes_none() -> None:
    service, player = _service_with_mock_player()
    service.apply_preset(service.presets.index("Rock"))
    player.set_equalizer.reset_mock()
    assert service.apply_preset(PRESET_NONE) is True
    assert service.preset_index == PRESET_NONE
    player.set_equalizer.assert_called_once_with(None)


def test_apply_preset_invalid_index() -> None:
    service, _player = _service_with_mock_player()
    assert service.apply_preset(9999) is False


def test_dialog_lists_presets_and_emits(qtbot) -> None:
    service, _player = _service_with_mock_player()
    dialog = EqualizerDialog(service)
    qtbot.addWidget(dialog)
    # Off + all presets
    assert dialog.combo.count() == len(service.presets) + 1

    rock_pos = dialog.combo.findData(service.presets.index("Rock"))
    with qtbot.waitSignal(dialog.preset_selected) as blocker:
        dialog.combo.setCurrentIndex(rock_pos)
    assert blocker.args == [service.presets.index("Rock")]
    assert service.preset_index == service.presets.index("Rock")
