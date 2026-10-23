"""Tests for RemoteService HTTP routing (Task 3).

Fakes stand in for PlayerController / PlaylistModel and record the calls the
route handlers make, so we verify both the wiring and the input validation
(400s) without libVLC or the real Qt model.
"""

from __future__ import annotations

import json

import pytest
from PyQt6.QtNetwork import QHostAddress, QTcpSocket

from desktop_music.services.remote.remote_service import RemoteService


# -- fakes ----------------------------------------------------------------


class FakeTrack:
    def __init__(self, path, title=""):
        self.path = path
        self.title = title
        self.artist = ""
        self.duration_ms = 0
        self.start_ms = 0
        self.end_ms = 0

    @property
    def is_cue_track(self):
        return False

    @property
    def display_title(self):
        return self.title or self.path


class FakePlayMode:
    def __init__(self):
        self.shuffle = False

        class _R:
            value = "none"
        self.repeat = _R()


class FakeBackend:
    def get_state(self):
        class _S:
            value = "playing"
        return _S()

    def get_time(self):
        return 0

    def get_length(self):
        return 0

    def is_muted(self):
        return False

    def get_rate(self):
        return 1.0


class FakePlaylist:
    def __init__(self, n):
        self._tracks = [FakeTrack(f"/t{i}.mp3", f"T{i}") for i in range(n)]
        self.current_index = 0 if n else -1

    def rowCount(self):  # noqa: N802
        return len(self._tracks)

    def track_at(self, row):
        return self._tracks[row] if 0 <= row < len(self._tracks) else None

    def current_track(self):
        return self.track_at(self.current_index)

    def remove_row(self, row):
        # Mirror PlaylistModel.remove_row cursor bookkeeping.
        if not (0 <= row < len(self._tracks)):
            return
        del self._tracks[row]
        if not self._tracks:
            self.current_index = -1
        elif row < self.current_index:
            self.current_index -= 1
        elif row == self.current_index:
            self.current_index = min(self.current_index, len(self._tracks) - 1)


class FakeController:
    def __init__(self, playlist):
        self.playlist = playlist
        self.backend = FakeBackend()
        self.volume = 50
        self.play_mode = FakePlayMode()
        self.calls = []
        self.remote_mode = False
        self.remote_report = None

    def set_remote_mode(self, enabled):
        self.remote_mode = bool(enabled)
        self.calls.append(("set_remote_mode", bool(enabled)))

    def set_remote_report(self, *, position_ms, length_ms, state):
        self.remote_report = {
            "position_ms": position_ms,
            "length_ms": length_ms,
            "state": state,
        }

    def dispatch(self, command_id):
        self.calls.append(("dispatch", command_id))

    def set_volume(self, value):
        self.calls.append(("set_volume", value))
        self.volume = value

    def seek_to_fraction(self, fraction):
        self.calls.append(("seek_to_fraction", fraction))

    def seek_to_ms(self, ms):
        self.calls.append(("seek_to_ms", ms))

    def play_row(self, row):
        self.calls.append(("play_row", row))
        self.playlist.current_index = row


# -- HTTP client helper (signal-driven, pumped by qtbot) ------------------


def _request(qtbot, port, method, path, body=b"", headers=None):
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
    lines = [f"{method} {path} HTTP/1.1", "Host: localhost"]
    hdrs = headers or {}
    if body:
        hdrs.setdefault("Content-Length", str(len(body)))
    for k, v in hdrs.items():
        lines.append(f"{k}: {v}")
    raw = ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body
    sock.write(raw)
    sock.flush()
    qtbot.waitUntil(lambda: done["flag"] or b"\r\n\r\n" in bytes(received), timeout=3000)
    sock.close()
    head, _, payload = bytes(received).partition(b"\r\n\r\n")
    status = int(head.split(b"\r\n")[0].decode("latin-1").split(" ")[1])
    return status, payload


@pytest.fixture
def svc(qtbot):
    playlist = FakePlaylist(3)
    controller = FakeController(playlist)
    service = RemoteService(controller, playlist, http_port=0)
    assert service.start(QHostAddress(QHostAddress.SpecialAddress.LocalHost))
    yield service, controller, playlist
    service.stop()


def test_ping(svc, qtbot):
    service, _, _ = svc
    status, body = _request(qtbot, service.http_port, "GET", "/api/ping")
    assert status == 200
    assert json.loads(body)["ok"] is True


def test_get_state(svc, qtbot):
    service, _, _ = svc
    status, body = _request(qtbot, service.http_port, "GET", "/api/state")
    assert status == 200
    data = json.loads(body)
    assert data["state"] == "playing"
    assert data["volume"] == 50
    assert data["current"]["title"] == "T0"


def test_get_playlist(svc, qtbot):
    service, _, _ = svc
    status, body = _request(qtbot, service.http_port, "GET", "/api/playlist")
    assert status == 200
    data = json.loads(body)
    assert data["count"] == 3
    assert [t["title"] for t in data["tracks"]] == ["T0", "T1", "T2"]


def test_command_dispatch(svc, qtbot):
    service, controller, _ = svc
    status, _ = _request(qtbot, service.http_port, "POST", "/api/command/play_pause")
    assert status == 200
    assert ("dispatch", "play_pause") in controller.calls


def test_command_unknown_400(svc, qtbot):
    service, controller, _ = svc
    status, body = _request(qtbot, service.http_port, "POST", "/api/command/frobnicate")
    assert status == 400
    assert "unknown command" in json.loads(body)["error"]
    assert controller.calls == []


def test_volume_set(svc, qtbot):
    service, controller, _ = svc
    status, _ = _request(
        qtbot, service.http_port, "POST", "/api/volume", body=b'{"value": 80}'
    )
    assert status == 200
    assert ("set_volume", 80) in controller.calls


def test_volume_out_of_range_400(svc, qtbot):
    service, controller, _ = svc
    status, _ = _request(
        qtbot, service.http_port, "POST", "/api/volume", body=b'{"value": 150}'
    )
    assert status == 400
    assert controller.calls == []


def test_seek_fraction(svc, qtbot):
    service, controller, _ = svc
    status, _ = _request(
        qtbot, service.http_port, "POST", "/api/seek", body=b'{"fraction": 0.5}'
    )
    assert status == 200
    assert ("seek_to_fraction", 0.5) in controller.calls


def test_seek_ms(svc, qtbot):
    service, controller, _ = svc
    status, _ = _request(
        qtbot, service.http_port, "POST", "/api/seek", body=b'{"ms": 12000}'
    )
    assert status == 200
    assert ("seek_to_ms", 12000) in controller.calls


def test_seek_missing_field_400(svc, qtbot):
    service, controller, _ = svc
    status, _ = _request(
        qtbot, service.http_port, "POST", "/api/seek", body=b'{"foo": 1}'
    )
    assert status == 400
    assert controller.calls == []


def test_play_index(svc, qtbot):
    service, controller, _ = svc
    status, _ = _request(
        qtbot, service.http_port, "POST", "/api/play", body=b'{"index": 2}'
    )
    assert status == 200
    assert ("play_row", 2) in controller.calls


def test_play_index_out_of_range_400(svc, qtbot):
    service, controller, _ = svc
    status, _ = _request(
        qtbot, service.http_port, "POST", "/api/play", body=b'{"index": 9}'
    )
    assert status == 400
    assert controller.calls == []


def test_serves_remote_page_at_root(svc, qtbot):
    service, _, _ = svc
    status, body = _request(qtbot, service.http_port, "GET", "/")
    assert status == 200
    text = body.decode("utf-8")
    assert "<!DOCTYPE html>" in text or "<!doctype html>" in text
    assert "</html>" in text


def test_serves_remote_page_at_remote(svc, qtbot):
    service, _, _ = svc
    status, body = _request(qtbot, service.http_port, "GET", "/remote")
    assert status == 200
    assert b"</html>" in body


def test_cover_404_when_no_art(svc, qtbot):
    # FakeTrack paths are not real files, so no cover is available.
    service, _, _ = svc
    status, body = _request(qtbot, service.http_port, "GET", "/api/cover/0")
    assert status == 404
    assert "no cover art" in json.loads(body)["error"]


def test_cover_404_when_index_out_of_range(svc, qtbot):
    service, _, _ = svc
    status, body = _request(qtbot, service.http_port, "GET", "/api/cover/99")
    assert status == 404
    assert "track not found" in json.loads(body)["error"]


def test_cover_400_when_index_not_integer(svc, qtbot):
    service, _, _ = svc
    status, body = _request(qtbot, service.http_port, "GET", "/api/cover/abc")
    assert status == 400
    assert "integer" in json.loads(body)["error"]


def test_cover_200_with_embedded_art(qtbot, tmp_path):
    import math
    import struct
    import wave

    from mutagen.wave import WAVE
    from mutagen.id3 import APIC

    from PyQt6.QtCore import QBuffer, QByteArray
    from PyQt6.QtGui import QColor, QImage

    img = QImage(4, 4, QImage.Format.Format_RGB32)
    img.fill(QColor(200, 100, 50))
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    png = bytes(ba.data())

    path = tmp_path / "song.wav"
    rate = 8000
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(rate // 4):
            frames += struct.pack("<h", int(10000 * math.sin(2 * math.pi * 440 * i / rate)))
        w.writeframes(bytes(frames))
    audio = WAVE(str(path))
    if audio.tags is None:
        audio.add_tags()
    audio.tags.add(APIC(encoding=3, mime="image/png", type=3, desc="", data=png))
    audio.save()

    playlist = FakePlaylist(0)
    playlist._tracks = [FakeTrack(str(path), "Song")]
    playlist.current_index = 0
    controller = FakeController(playlist)
    service = RemoteService(controller, playlist, http_port=0)
    assert service.start(QHostAddress(QHostAddress.SpecialAddress.LocalHost))
    try:
        status, body = _request(qtbot, service.http_port, "GET", "/api/cover/0")
        assert status == 200
        assert body == png
    finally:
        service.stop()


# -- /api/audio/{index} ---------------------------------------------------


import shutil  # noqa: E402

_HAS_FFMPEG = shutil.which("ffmpeg") is not None
_ffmpeg_required = pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg not installed")


def _make_wav_file(path, seconds=1.0, rate=8000):
    import struct
    import wave

    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<" + "h" * frames, *([0] * frames)))
    return path


def test_audio_400_when_index_not_integer(svc, qtbot):
    service, _, _ = svc
    status, _ = _request(qtbot, service.http_port, "GET", "/api/audio/abc")
    assert status == 400


def test_audio_404_when_index_out_of_range(svc, qtbot):
    service, _, _ = svc
    status, _ = _request(qtbot, service.http_port, "GET", "/api/audio/99")
    assert status == 404


@_ffmpeg_required
def test_audio_streams_mp3(qtbot, tmp_path, monkeypatch):
    # Point the transcode cache at a temp dir so tests don't touch ~/.cache.
    from desktop_music.services.remote import transcode as tc

    cache = tc.TranscodeCache(tmp_path / "cache")
    monkeypatch.setattr(tc, "get_default_cache", lambda: cache)

    src = _make_wav_file(tmp_path / "song.wav", seconds=1.0)
    playlist = FakePlaylist(0)
    playlist._tracks = [FakeTrack(str(src), "Song")]
    playlist.current_index = 0
    controller = FakeController(playlist)
    service = RemoteService(controller, playlist, http_port=0)
    assert service.start(QHostAddress(QHostAddress.SpecialAddress.LocalHost))
    try:
        status, body = _request(qtbot, service.http_port, "GET", "/api/audio/0")
        assert status == 200
        assert len(body) > 0
        head = body[:3]
        assert head[:2] in (b"\xff\xfb", b"\xff\xf3") or head == b"ID3"
    finally:
        service.stop()


@_ffmpeg_required
def test_audio_cue_segment_passed(qtbot, tmp_path, monkeypatch):
    # Verify the handler forwards the track's cue start/end into transcode.
    from desktop_music.services.remote import transcode as tc

    seen = {}

    def fake_transcode(path, start_ms=0, end_ms=0, **kw):
        seen["args"] = (path, start_ms, end_ms)
        out = tmp_path / "out.mp3"
        out.write_bytes(b"ID3fake")
        return out

    monkeypatch.setattr(tc, "transcode_to_mp3", fake_transcode)

    src = _make_wav_file(tmp_path / "album.wav", seconds=3.0)
    track = FakeTrack(str(src), "Track 2")
    track.start_ms = 1000
    track.end_ms = 2000
    playlist = FakePlaylist(0)
    playlist._tracks = [track]
    playlist.current_index = 0
    controller = FakeController(playlist)
    service = RemoteService(controller, playlist, http_port=0)
    assert service.start(QHostAddress(QHostAddress.SpecialAddress.LocalHost))
    try:
        status, _ = _request(qtbot, service.http_port, "GET", "/api/audio/0")
        assert status == 200
        assert seen["args"] == (str(src), 1000, 2000)
    finally:
        service.stop()


# -- /api/remove ----------------------------------------------------------


def test_remove_400_without_index(svc, qtbot):
    service, _, _ = svc
    status, _ = _request(qtbot, service.http_port, "POST", "/api/remove", body=b"{}")
    assert status == 400


def test_remove_400_when_index_out_of_range(svc, qtbot):
    service, _, _ = svc
    status, _ = _request(
        qtbot, service.http_port, "POST", "/api/remove", body=b'{"index": 99}'
    )
    assert status == 400


def test_remove_deletes_track(svc, qtbot):
    service, _, playlist = svc
    assert playlist.rowCount() == 3
    status, body = _request(
        qtbot, service.http_port, "POST", "/api/remove", body=b'{"index": 1}'
    )
    assert status == 200
    assert playlist.rowCount() == 2
    # Remaining titles are T0, T2 (T1 removed).
    assert [t.title for t in playlist._tracks] == ["T0", "T2"]


def test_remove_before_current_shifts_index(svc, qtbot):
    service, _, playlist = svc
    playlist.current_index = 2  # playing the last track
    status, body = _request(
        qtbot, service.http_port, "POST", "/api/remove", body=b'{"index": 0}'
    )
    assert status == 200
    # Removing an earlier row keeps the same track current (index 2 -> 1).
    assert playlist.current_index == 1
    data = json.loads(body)
    assert data["current_index"] == 1


def test_remove_current_advances_to_next(svc, qtbot):
    service, _, playlist = svc
    playlist.current_index = 1
    status, body = _request(
        qtbot, service.http_port, "POST", "/api/remove", body=b'{"index": 1}'
    )
    assert status == 200
    # The current track was removed; cursor now points at the next track,
    # which has shifted into index 1 (was T2).
    assert playlist.current_index == 1
    assert playlist.current_track().title == "T2"


# -- /api/audio/claim + /api/audio/release --------------------------------


def test_claim_enters_remote_mode(svc, qtbot):
    service, controller, _ = svc
    assert controller.remote_mode is False
    status, body = _request(
        qtbot, service.http_port, "POST", "/api/audio/claim",
        body=b'{"token": "t1"}',
    )
    assert status == 200
    assert controller.remote_mode is True
    assert json.loads(body)["audio_token"] == "t1"


def test_claim_without_token_generates_one(svc, qtbot):
    service, controller, _ = svc
    status, body = _request(
        qtbot, service.http_port, "POST", "/api/audio/claim", body=b"{}"
    )
    assert status == 200
    assert controller.remote_mode is True
    assert json.loads(body)["audio_token"]  # non-empty server-generated token


def test_second_client_claim_conflicts(svc, qtbot):
    service, controller, _ = svc
    status, _ = _request(
        qtbot, service.http_port, "POST", "/api/audio/claim",
        body=b'{"token": "first"}',
    )
    assert status == 200
    # A different client cannot steal the audio while the first holds it.
    status, body = _request(
        qtbot, service.http_port, "POST", "/api/audio/claim",
        body=b'{"token": "second"}',
    )
    assert status == 409
    assert "already claimed" in json.loads(body)["error"]
    assert controller.remote_mode is True


def test_same_client_reclaim_refreshes(svc, qtbot):
    service, controller, _ = svc
    for _ in range(2):
        status, body = _request(
            qtbot, service.http_port, "POST", "/api/audio/claim",
            body=b'{"token": "mine"}',
        )
        assert status == 200
    assert json.loads(body)["audio_token"] == "mine"
    assert controller.remote_mode is True


def test_release_restores_desktop_audio(svc, qtbot):
    service, controller, _ = svc
    _request(qtbot, service.http_port, "POST", "/api/audio/claim",
             body=b'{"token": "t1"}')
    assert controller.remote_mode is True
    status, body = _request(
        qtbot, service.http_port, "POST", "/api/audio/release",
        body=b'{"token": "t1"}',
    )
    assert status == 200
    assert controller.remote_mode is False
    assert json.loads(body)["audio_token"] is None
    # After release a new client can claim.
    status, _ = _request(
        qtbot, service.http_port, "POST", "/api/audio/claim",
        body=b'{"token": "t2"}',
    )
    assert status == 200
    assert controller.remote_mode is True


def test_release_with_wrong_token_is_ignored(svc, qtbot):
    service, controller, _ = svc
    _request(qtbot, service.http_port, "POST", "/api/audio/claim",
             body=b'{"token": "owner"}')
    status, _ = _request(
        qtbot, service.http_port, "POST", "/api/audio/release",
        body=b'{"token": "intruder"}',
    )
    assert status == 200
    # The real owner still holds the claim.
    assert controller.remote_mode is True


def test_remote_state_requires_matching_token(svc, qtbot):
    service, controller, _ = svc
    _request(qtbot, service.http_port, "POST", "/api/audio/claim",
             body=b'{"token": "holder"}')
    # Report with the wrong token is ignored (not the audio source).
    _request(
        qtbot, service.http_port, "POST", "/api/remote/state",
        body=b'{"token": "other", "position_ms": 5000, "length_ms": 9000, "state": "playing"}',
    )
    assert controller.remote_report is None
    # Report with the holder's token is mirrored.
    _request(
        qtbot, service.http_port, "POST", "/api/remote/state",
        body=b'{"token": "holder", "position_ms": 5000, "length_ms": 9000, "state": "playing"}',
    )
    assert controller.remote_report == {
        "position_ms": 5000, "length_ms": 9000, "state": "playing",
    }


def test_claim_expires_after_timeout(svc, qtbot, monkeypatch):
    service, controller, _ = svc
    import desktop_music.services.remote.remote_service as rs

    status, _ = _request(
        qtbot, service.http_port, "POST", "/api/audio/claim",
        body=b'{"token": "t1"}',
    )
    assert status == 200
    assert controller.remote_mode is True

    # Simulate the heartbeat lapsing past the timeout, then run the sweep.
    service._claim_seen -= (rs._CLAIM_TIMEOUT_S + 1.0)
    service._expire_stale_claim()
    assert service._claim_token is None
    assert controller.remote_mode is False

    # With the claim expired, a different client may now claim.
    status, _ = _request(
        qtbot, service.http_port, "POST", "/api/audio/claim",
        body=b'{"token": "t2"}',
    )
    assert status == 200
    assert controller.remote_mode is True
