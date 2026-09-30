"""Tests for the customizable shortcut system (Task 14)."""

from __future__ import annotations

from unittest.mock import MagicMock

from PyQt6.QtWidgets import QWidget

from desktop_music.core import commands as cmd
from desktop_music.core.shortcuts import ShortcutManager
from desktop_music.ui.shortcut_dialog import ShortcutDialog


def _manager(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    dispatched = []
    mgr = ShortcutManager(host, dispatched.append)
    mgr.rebind_all()
    return mgr, dispatched, host


def test_defaults_loaded(qtbot) -> None:
    mgr, _d, _h = _manager(qtbot)
    assert mgr.shortcut_for(cmd.PLAY_PAUSE) == "Space"
    assert set(mgr.mapping) == {c.id for c in cmd.COMMANDS}


def test_reassign_shortcut(qtbot) -> None:
    mgr, _d, _h = _manager(qtbot)
    assert mgr.set_shortcut(cmd.PLAY_PAUSE, "P") is True
    assert mgr.shortcut_for(cmd.PLAY_PAUSE) == "P"


def test_conflict_detection(qtbot) -> None:
    mgr, _d, _h = _manager(qtbot)
    # Space is play_pause by default; assigning it to STOP should conflict
    assert mgr.set_shortcut(cmd.STOP, "Space") is False
    conflict = mgr.conflict_for("Space", exclude=cmd.STOP)
    assert conflict == cmd.PLAY_PAUSE


def test_conflict_normalized_spelling(qtbot) -> None:
    mgr, _d, _h = _manager(qtbot)
    mgr.set_shortcut(cmd.SNAPSHOT, "Ctrl+S")
    # different spelling, same sequence -> conflict
    assert mgr.conflict_for("ctrl+s", exclude=cmd.NEXT) == cmd.SNAPSHOT


def test_reset_defaults(qtbot) -> None:
    mgr, _d, _h = _manager(qtbot)
    mgr.set_shortcut(cmd.PLAY_PAUSE, "P")
    mgr.reset_defaults()
    assert mgr.shortcut_for(cmd.PLAY_PAUSE) == "Space"


def test_state_roundtrip(qtbot) -> None:
    mgr, _d, _h = _manager(qtbot)
    mgr.set_shortcut(cmd.MUTE, "Ctrl+M")
    state = mgr.to_state()

    host2 = QWidget()
    qtbot.addWidget(host2)
    mgr2 = ShortcutManager(host2, lambda _cid: None)
    mgr2.load_state(state)
    assert mgr2.shortcut_for(cmd.MUTE) == "Ctrl+M"
    # unspecified commands fall back to defaults
    assert mgr2.shortcut_for(cmd.PLAY_PAUSE) == "Space"


def test_load_state_adds_new_command_defaults(qtbot) -> None:
    mgr, _d, _h = _manager(qtbot)
    # simulate an old state file missing a newer command
    mgr.load_state({cmd.PLAY_PAUSE: "P"})
    assert mgr.shortcut_for(cmd.PLAY_PAUSE) == "P"
    assert mgr.shortcut_for(cmd.SNAPSHOT) == cmd.COMMANDS_BY_ID[cmd.SNAPSHOT].default_shortcut


# -- dialog ----------------------------------------------------------------


def test_dialog_lists_all_commands(qtbot) -> None:
    host = QWidget()
    qtbot.addWidget(host)
    mgr = ShortcutManager(host, lambda _cid: None)
    dialog = ShortcutDialog(mgr)
    qtbot.addWidget(dialog)
    assert dialog.table.rowCount() == len(cmd.COMMANDS)


def test_dialog_assign_emits(qtbot) -> None:
    host = QWidget()
    qtbot.addWidget(host)
    mgr = ShortcutManager(host, lambda _cid: None)
    dialog = ShortcutDialog(mgr)
    qtbot.addWidget(dialog)
    dialog.table.setCurrentCell(0, 0)  # first command
    from PyQt6.QtGui import QKeySequence

    dialog._editor.setKeySequence(QKeySequence("Ctrl+Alt+P"))
    with qtbot.waitSignal(dialog.shortcuts_changed):
        dialog._assign()
    cid = cmd.COMMANDS[0].id
    assert mgr.shortcut_for(cid) == "Ctrl+Alt+P"


# -- window integration ----------------------------------------------------


def test_window_dispatch_routes_fullscreen_and_snapshot(qtbot, tmp_path) -> None:
    from desktop_music.core.controller import PlayerController
    from desktop_music.services.backend import PlaybackState
    from desktop_music.services.settings import SettingsStore
    from desktop_music.ui.main_window import MainWindow

    backend = MagicMock()
    backend.get_state.return_value = PlaybackState.IDLE
    backend.get_time.return_value = 0
    backend.get_length.return_value = 0
    backend.get_volume.return_value = 80
    backend.is_muted.return_value = False
    controller = PlayerController(backend=backend)
    controller._timer.stop()
    window = MainWindow(
        controller=controller, settings=SettingsStore(str(tmp_path / "s.json"))
    )
    qtbot.addWidget(window)

    window.toggle_fullscreen = MagicMock()
    window.dispatch_command(cmd.FULLSCREEN)
    window.toggle_fullscreen.assert_called_once()

    # non-window command routes to controller
    window.dispatch_command(cmd.PLAY_PAUSE)
    backend.toggle_pause.assert_called_once()
