"""Tests for the audio normalizer (normvol) on/off toggle.

The toggle rebuilds the libVLC backend (audio filters are fixed at instance
creation) and restores playback state. These tests cover:
  * the backend-rebuild + state-restore sequence (with a mocked backend
    factory, so no real audio device is needed and calls are inspectable),
  * the ``normalize_changed`` signal,
  * the controller's deferred resume-seek applied from ``_poll``,
  * persistence of the setting through the main window,
  * end-to-end behaviour against real libVLC.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

import desktop_music.core.controller as controller_mod
from desktop_music.core.controller import PlayerController
from desktop_music.services.backend import PlaybackState


def _playing_backend_mock(
    *, normalize: bool, path: str | None, volume: int = 50
) -> MagicMock:
    b = MagicMock()
    b.normalize = normalize
    b.current_path = path
    b.is_playing.return_value = True
    b.get_state.return_value = PlaybackState.PLAYING
    b.get_time.return_value = 12_345
    b.is_muted.return_value = False
    b.get_rate.return_value = 1.0
    b.get_volume.return_value = volume
    # set_volume echoes the clamped value like the real backend
    b.set_volume.side_effect = lambda v: max(0, min(100, int(v)))
    return b


def _make_controller_with_mock(monkeypatch, initial: MagicMock) -> PlayerController:
    initial.get_state.return_value = PlaybackState.IDLE
    ctrl = PlayerController(backend=initial)
    ctrl._timer.stop()
    return ctrl


# -- controller: rebuild + restore ----------------------------------------


def test_set_normalize_rebuilds_backend_and_restores_state(monkeypatch) -> None:
    old = _playing_backend_mock(normalize=False, path="/tmp/song.flac", volume=63)
    new = _playing_backend_mock(normalize=True, path=None, volume=0)

    ctrl = _make_controller_with_mock(monkeypatch, old)
    # pretend media is loaded & playing at a position with a custom volume
    ctrl._volume = 63

    # intercept the VLCBackend constructor used inside set_normalize
    created = {}

    def fake_factory(normalize=False):
        created["normalize"] = normalize
        return new

    monkeypatch.setattr(controller_mod, "VLCBackend", fake_factory)

    ctrl.set_normalize(True)

    # new backend created with normalize=True and swapped in
    assert created["normalize"] is True
    assert ctrl.backend is new
    old.release.assert_called_once()

    # state restored onto the new backend
    new.set_volume.assert_any_call(63)
    new.set_muted.assert_called_once_with(False)
    new.set_rate.assert_called_once_with(1.0)
    new.load.assert_called_once_with("/tmp/song.flac")
    new.play.assert_called_once()
    assert ctrl.normalize is True


def test_set_normalize_noop_when_unchanged(monkeypatch) -> None:
    old = _playing_backend_mock(normalize=False, path=None)
    ctrl = _make_controller_with_mock(monkeypatch, old)

    called = {"n": 0}
    monkeypatch.setattr(
        controller_mod,
        "VLCBackend",
        lambda normalize=False: called.__setitem__("n", called["n"] + 1),
    )
    ctrl.set_normalize(False)  # already off
    assert called["n"] == 0
    assert ctrl.backend is old


def test_normalize_changed_signal_emitted(qtbot, monkeypatch) -> None:
    old = _playing_backend_mock(normalize=False, path=None)
    new = _playing_backend_mock(normalize=True, path=None)
    ctrl = _make_controller_with_mock(monkeypatch, old)
    monkeypatch.setattr(controller_mod, "VLCBackend", lambda normalize=False: new)

    with qtbot.waitSignal(ctrl.normalize_changed) as blocker:
        ctrl.set_normalize(True)
    assert blocker.args == [True]


def test_backend_rebuilt_hook_called_with_new_backend(monkeypatch) -> None:
    old = _playing_backend_mock(normalize=False, path=None)
    new = _playing_backend_mock(normalize=True, path=None)
    ctrl = _make_controller_with_mock(monkeypatch, old)
    monkeypatch.setattr(controller_mod, "VLCBackend", lambda normalize=False: new)

    seen = {}
    ctrl.set_backend_rebuilt_hook(lambda b: seen.setdefault("backend", b))
    ctrl.set_normalize(True)
    assert seen["backend"] is new


def test_toggle_normalize_flips_and_returns_state(monkeypatch) -> None:
    old = _playing_backend_mock(normalize=False, path=None)
    new = _playing_backend_mock(normalize=True, path=None)
    ctrl = _make_controller_with_mock(monkeypatch, old)
    monkeypatch.setattr(controller_mod, "VLCBackend", lambda normalize=False: new)

    assert ctrl.toggle_normalize() is True
    assert ctrl.normalize is True


def test_resume_seek_applied_from_poll(monkeypatch) -> None:
    """After a rebuild the controller defers the resume-seek until the new
    player is actually playing, applied on the next _poll tick."""
    old = _playing_backend_mock(normalize=False, path="/tmp/x.flac")
    new = _playing_backend_mock(normalize=True, path=None)
    # new backend starts "opening", then transitions to playing
    new.get_state.side_effect = [PlaybackState.OPENING, PlaybackState.PLAYING]

    ctrl = _make_controller_with_mock(monkeypatch, old)
    monkeypatch.setattr(controller_mod, "VLCBackend", lambda normalize=False: new)

    ctrl.set_normalize(True)
    assert ctrl._resume_pending is True

    # first poll: still opening -> no seek yet
    ctrl._poll()
    # second poll: playing -> resume seek applied to the snapshotted position
    ctrl._poll()
    new.seek.assert_called_with(12_345)
    assert ctrl._resume_pending is False


# -- main window integration ----------------------------------------------


def _make_window(qtbot):
    from desktop_music.ui.main_window import MainWindow

    backend = MagicMock()
    backend.normalize = False
    backend.get_state.return_value = PlaybackState.IDLE
    backend.get_time.return_value = 0
    backend.get_length.return_value = 0
    backend.get_volume.return_value = 50
    backend.set_volume.side_effect = lambda v: max(0, min(100, int(v)))
    backend.is_muted.return_value = False
    ctrl = PlayerController(backend=backend)
    ctrl._timer.stop()
    window = MainWindow(controller=ctrl)
    qtbot.addWidget(window)
    return window


def test_window_has_checkable_normalizer_action(qtbot) -> None:
    window = _make_window(qtbot)
    assert window._act_normalize is not None
    assert window._act_normalize.isCheckable()
    assert window._act_normalize.isChecked() is False


def test_window_save_state_includes_normalize(qtbot) -> None:
    window = _make_window(qtbot)
    window._settings.update = MagicMock()
    window._save_state()
    saved = window._settings.update.call_args[0][0]
    assert "normalize" in saved
    assert saved["normalize"] is False


# -- end-to-end against real libVLC ---------------------------------------


@pytest.fixture
def tone_wav(tmp_path) -> str:
    import math
    import struct
    import wave

    path = tmp_path / "tone.wav"
    rate = 44100
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(rate):  # 1 second
            s = int(32767 * 0.3 * math.sin(2 * math.pi * 440 * i / rate))
            frames += struct.pack("<h", s)
        w.writeframes(bytes(frames))
    return str(path)


def test_real_backend_toggle_preserves_track_and_volume(tone_wav) -> None:
    ctrl = PlayerController()
    try:
        assert ctrl.normalize is False
        ctrl.open(tone_wav, autoplay=True)
        for _ in range(40):
            if ctrl.backend.get_state() == PlaybackState.PLAYING:
                break
            time.sleep(0.05)
        ctrl.set_volume(63)
        old_backend = ctrl.backend

        ctrl.toggle_normalize()

        assert ctrl.normalize is True
        assert ctrl.backend is not old_backend
        assert ctrl.backend.current_path == tone_wav
        assert ctrl.volume == 63
    finally:
        ctrl.shutdown()
