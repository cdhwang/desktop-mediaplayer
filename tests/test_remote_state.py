"""Tests for remote state serialization (Task 1 of the remote-control feature).

These use lightweight fakes instead of the real VLC backend / Qt model so
they run fast and headless, verifying only the JSON shapes that the Android
client depends on.
"""

from __future__ import annotations

from desktop_music.services.remote import state as rstate


class FakeTrack:
    def __init__(self, path, title="", artist="", duration_ms=0, start_ms=0, end_ms=0):
        self.path = path
        self.title = title
        self.artist = artist
        self.duration_ms = duration_ms
        self.start_ms = start_ms
        self.end_ms = end_ms

    @property
    def is_cue_track(self):
        return self.start_ms > 0 or self.end_ms > 0

    @property
    def display_title(self):
        if self.title:
            return f"{self.artist} - {self.title}" if self.artist else self.title
        import os

        return os.path.basename(self.path)


class FakePlaylist:
    def __init__(self, tracks, current=-1):
        self._tracks = tracks
        self._current = current

    def rowCount(self):  # noqa: N802 - mirrors Qt API
        return len(self._tracks)

    def track_at(self, row):
        if 0 <= row < len(self._tracks):
            return self._tracks[row]
        return None

    @property
    def current_index(self):
        return self._current

    def current_track(self):
        return self.track_at(self._current)


class FakeBackend:
    def __init__(self, state="playing", time_ms=1000, length_ms=200000,
                 muted=False, rate=1.0):
        self._state = state
        self._time = time_ms
        self._length = length_ms
        self._muted = muted
        self._rate = rate

    def get_state(self):
        # emulate an enum member with a ``.value`` attribute
        class _S:
            pass
        s = _S()
        s.value = self._state
        return s

    def get_time(self):
        return self._time

    def get_length(self):
        return self._length

    def is_muted(self):
        return self._muted

    def get_rate(self):
        return self._rate


class FakePlayMode:
    def __init__(self, shuffle=False, repeat="none"):
        self.shuffle = shuffle

        class _R:
            value = repeat
        self.repeat = _R()


class FakeController:
    def __init__(self, backend, playlist, volume=70, play_mode=None):
        self.backend = backend
        self.playlist = playlist
        self.volume = volume
        self.play_mode = play_mode or FakePlayMode()


def test_build_track_basic():
    t = FakeTrack("/music/song.mp3", title="Song", artist="Artist", duration_ms=1234)
    d = rstate.build_track(t, 3, playing=True)
    assert d == {
        "index": 3,
        "title": "Artist - Song",
        "raw_title": "Song",
        "artist": "Artist",
        "duration_ms": 1234,
        "playing": True,
        "is_cue_track": False,
    }


def test_build_track_fallback_to_filename():
    t = FakeTrack("/music/no_tags.flac")
    d = rstate.build_track(t, 0, playing=False)
    assert d["title"] == "no_tags.flac"
    assert d["raw_title"] == ""
    assert d["artist"] == ""


def test_build_playlist_shape_and_current_flag():
    tracks = [
        FakeTrack("/a.mp3", title="A"),
        FakeTrack("/b.mp3", title="B"),
        FakeTrack("/c.mp3", title="C"),
    ]
    pl = FakePlaylist(tracks, current=1)
    d = rstate.build_playlist(pl)
    assert d["count"] == 3
    assert d["current_index"] == 1
    assert [t["playing"] for t in d["tracks"]] == [False, True, False]
    assert [t["index"] for t in d["tracks"]] == [0, 1, 2]


def test_build_playlist_empty():
    d = rstate.build_playlist(FakePlaylist([], current=-1))
    assert d == {"count": 0, "current_index": -1, "tracks": []}

    d2 = rstate.build_playlist(None)
    assert d2 == {"count": 0, "current_index": -1, "tracks": []}


def test_build_state_snapshot_full():
    tracks = [FakeTrack("/a.mp3", title="A", artist="X", duration_ms=5000)]
    pl = FakePlaylist(tracks, current=0)
    backend = FakeBackend(state="playing", time_ms=1500, length_ms=5000,
                          muted=False, rate=1.25)
    ctrl = FakeController(backend, pl, volume=65,
                          play_mode=FakePlayMode(shuffle=True, repeat="all"))
    snap = rstate.build_state_snapshot(ctrl)
    assert snap["state"] == "playing"
    assert snap["position_ms"] == 1500
    assert snap["length_ms"] == 5000
    assert snap["volume"] == 65
    assert snap["muted"] is False
    assert snap["shuffle"] is True
    assert snap["repeat"] == "all"
    assert snap["rate"] == 1.25
    assert snap["current_index"] == 0
    assert snap["current"]["title"] == "X - A"
    assert snap["current"]["playing"] is True


def test_build_state_snapshot_nothing_loaded():
    pl = FakePlaylist([], current=-1)
    backend = FakeBackend(state="idle", time_ms=-1, length_ms=0)
    ctrl = FakeController(backend, pl, volume=100)
    snap = rstate.build_state_snapshot(ctrl)
    assert snap["state"] == "idle"
    assert snap["position_ms"] == 0  # -1 sentinel clamped
    assert snap["length_ms"] == 0
    assert snap["current_index"] == -1
    assert snap["current"] is None


def test_build_state_snapshot_defaults_playlist_from_controller():
    tracks = [FakeTrack("/a.mp3", title="A")]
    pl = FakePlaylist(tracks, current=0)
    backend = FakeBackend()
    ctrl = FakeController(backend, pl)
    # Do not pass playlist explicitly; it should be read from controller.
    snap = rstate.build_state_snapshot(ctrl)
    assert snap["current"]["title"] == "A"
