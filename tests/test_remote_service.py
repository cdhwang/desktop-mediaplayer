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


class FakeController:
    def __init__(self, playlist):
        self.playlist = playlist
        self.backend = FakeBackend()
        self.volume = 50
        self.play_mode = FakePlayMode()
        self.calls = []

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
