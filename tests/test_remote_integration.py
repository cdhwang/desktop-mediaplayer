"""Integration tests for remote control wired into MainWindow (Task 6).

These build a real MainWindow (headless offscreen) and exercise the remote
toggle, the persisted setting, and a live HTTP round-trip against the running
service.
"""

from __future__ import annotations

import json

import pytest
from PyQt6.QtNetwork import QHostAddress, QTcpSocket

from desktop_music.services.settings import SettingsStore
from desktop_music.ui.main_window import MainWindow


@pytest.fixture
def window(qtbot, tmp_path):
    settings = SettingsStore(str(tmp_path / "state.json"))
    win = MainWindow(settings=settings)
    qtbot.addWidget(win)
    yield win
    win.stop_remote()


def _http_get(qtbot, port, path):
    sock = QTcpSocket()
    received = bytearray()
    done = {"flag": False}
    sock.readyRead.connect(lambda: received.extend(bytes(sock.readAll().data())))

    def _disc():
        received.extend(bytes(sock.readAll().data()))
        done["flag"] = True

    sock.disconnected.connect(_disc)
    sock.connectToHost(QHostAddress(QHostAddress.SpecialAddress.LocalHost), port)
    qtbot.waitUntil(
        lambda: sock.state() == QTcpSocket.SocketState.ConnectedState, timeout=3000
    )
    sock.write(f"GET {path} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode("latin-1"))
    sock.flush()
    qtbot.waitUntil(lambda: done["flag"] or b"\r\n\r\n" in bytes(received), timeout=3000)
    sock.close()
    _head, _, payload = bytes(received).partition(b"\r\n\r\n")
    return payload


def test_remote_disabled_by_default(window):
    assert window.remote_enabled is False
    assert window.remote is None


def test_start_stop_remote(window, qtbot):
    assert window.start_remote() is True
    assert window.remote_enabled is True
    # Live HTTP ping against the running service on the default port.
    body = _http_get(qtbot, window.remote.http_port, "/api/ping")
    assert json.loads(body)["ok"] is True

    window.stop_remote()
    assert window.remote_enabled is False
    assert window.remote is None


def test_remote_setting_persisted_roundtrip(window):
    """Enabling remote is written to settings, and restore re-enables it.

    This avoids constructing a second MainWindow (each one spins up a real
    libVLC backend, and tearing several down in one process is flaky/unsafe
    in headless CI). Instead we verify the two halves directly: _save_state
    records the flag, and _restore_remote_state acts on it.
    """
    # Save side: starting remote then saving records remote_enabled=True.
    assert window.start_remote() is True
    window._save_state()
    assert window._settings.get("remote_enabled") is True
    window.stop_remote()

    # Save side: with remote off, the flag is recorded False.
    window._save_state()
    assert window._settings.get("remote_enabled") is False

    # Restore side: a saved "on" flag makes restore start the service.
    assert window.remote_enabled is False
    window._restore_remote_state({"remote_enabled": True})
    assert window.remote_enabled is True
    window.stop_remote()

    # Restore side: a saved "off" / missing flag leaves it stopped.
    window._restore_remote_state({"remote_enabled": False})
    assert window.remote_enabled is False
    window._restore_remote_state({})
    assert window.remote_enabled is False


def test_toggle_action_reflects_state(window, qtbot):
    # Toggling the menu action starts/stops the service.
    window._act_remote.setChecked(True)
    assert window.remote_enabled is True
    window._act_remote.setChecked(False)
    assert window.remote_enabled is False


def test_start_remote_enables_controller_remote_mode(window):
    """Starting the service puts the controller into browser-playback mode
    (muted, load-only); stopping it restores normal desktop playback."""
    controller = window._controller
    assert controller.remote_mode is False
    assert window.start_remote() is True
    assert controller.remote_mode is True
    assert controller.backend.is_muted() is True
    window.stop_remote()
    assert controller.remote_mode is False
    assert controller.backend.is_muted() is False
