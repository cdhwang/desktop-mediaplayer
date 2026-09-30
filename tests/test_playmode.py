"""Tests for play modes and JSON persistence (Task 5)."""

from __future__ import annotations

from desktop_music.core.playlist import PlaylistModel
from desktop_music.core.playmode import PlayMode, RepeatMode
from desktop_music.services.settings import SettingsStore


# -- play mode toggles -----------------------------------------------------


def test_toggle_shuffle() -> None:
    pm = PlayMode()
    assert pm.shuffle is False
    assert pm.toggle_shuffle() is True
    assert pm.shuffle is True


def test_cycle_repeat() -> None:
    pm = PlayMode()
    assert pm.repeat == RepeatMode.NONE
    assert pm.cycle_repeat() == RepeatMode.ALL
    assert pm.cycle_repeat() == RepeatMode.ONE
    assert pm.cycle_repeat() == RepeatMode.NONE


# -- next/previous decisions ----------------------------------------------


def test_next_row_natural_end_no_repeat_stops() -> None:
    pm = PlayMode()
    # at last track, natural end, no repeat -> stop (-1)
    assert pm.next_row(current=2, count=3, auto=True) == -1


def test_next_row_repeat_all_wraps() -> None:
    pm = PlayMode()
    pm.repeat = RepeatMode.ALL
    assert pm.next_row(current=2, count=3, auto=True) == 0


def test_next_row_repeat_one_replays_current() -> None:
    pm = PlayMode()
    pm.repeat = RepeatMode.ONE
    assert pm.next_row(current=1, count=3, auto=True) == 1


def test_explicit_next_always_advances_and_wraps() -> None:
    pm = PlayMode()
    # explicit next (auto=False) wraps even without repeat
    assert pm.next_row(current=2, count=3, auto=False) == 0
    assert pm.next_row(current=0, count=3, auto=False) == 1


def test_shuffle_picks_other_row() -> None:
    pm = PlayMode()
    pm.shuffle = True
    pm.seed(42)
    for _ in range(20):
        nxt = pm.next_row(current=1, count=5, auto=False)
        assert 0 <= nxt < 5


def test_previous_wraps() -> None:
    pm = PlayMode()
    assert pm.previous_row(current=0, count=3) == 2
    assert pm.previous_row(current=2, count=3) == 1


# -- play mode persistence -------------------------------------------------


def test_play_mode_state_roundtrip() -> None:
    pm = PlayMode()
    pm.shuffle = True
    pm.repeat = RepeatMode.ONE
    state = pm.to_state()

    restored = PlayMode()
    restored.load_state(state)
    assert restored.shuffle is True
    assert restored.repeat == RepeatMode.ONE


# -- settings store --------------------------------------------------------


def test_settings_roundtrip(tmp_path) -> None:
    path = str(tmp_path / "state.json")
    store = SettingsStore(path)
    store.set("volume", 42)
    store.set("play_mode", {"shuffle": True, "repeat": "all"})
    store.save()

    reopened = SettingsStore(path)
    data = reopened.load()
    assert data["volume"] == 42
    assert data["play_mode"]["repeat"] == "all"


def test_settings_missing_file_returns_empty(tmp_path) -> None:
    store = SettingsStore(str(tmp_path / "nope.json"))
    assert store.load() == {}


# -- playlist persistence --------------------------------------------------


def test_playlist_state_roundtrip_skips_missing(tmp_path) -> None:
    real = tmp_path / "a.mp3"
    real.write_bytes(b"")
    m = PlaylistModel()
    m.add_paths([str(real)])
    m._tracks.append(m._tracks[0].__class__(path=str(tmp_path / "gone.mp3")))
    state = m.to_state()

    restored = PlaylistModel()
    restored.load_state(state)
    # only the existing file survives
    assert restored.rowCount() == 1
    assert restored.track_at(0).path == str(real)
