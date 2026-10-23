"""Tests for the QTcpServer-based HTTP server (Task 2).

Uses a real QTcpSocket client against the server bound to a loopback port,
driven by the Qt event loop via qtbot.waitUntil.
"""

from __future__ import annotations

import json

import pytest
from PyQt6.QtNetwork import QHostAddress, QTcpSocket

from desktop_music.services.remote.http_server import (
    HttpServer,
    Request,
    Response,
    _match,
    _parse_range,
    _split_path,
)


# -- pure routing helpers (no Qt needed) ----------------------------------


def test_split_path():
    assert _split_path("/api/command/play_pause") == ["api", "command", "play_pause"]
    assert _split_path("/") == []
    assert _split_path("") == []


def test_match_literal_and_params():
    route = _split_path("/api/command/{id}")
    assert _match(route, _split_path("/api/command/next")) == {"id": "next"}
    assert _match(route, _split_path("/api/command")) is None
    assert _match(route, _split_path("/api/other/next")) is None


def test_response_json_helper():
    r = Response.json({"a": 1})
    assert r.status == 200
    assert json.loads(r.body) == {"a": 1}
    assert "application/json" in r.headers["Content-Type"]


def test_request_json_parsing():
    req = Request("POST", "/x", {}, {}, b'{"value": 42}')
    assert req.json() == {"value": 42}
    empty = Request("POST", "/x", {}, {}, b"")
    assert empty.json() is None
    bad = Request("POST", "/x", {}, {}, b"not json")
    assert bad.json() is None


# -- end-to-end over a real socket ----------------------------------------


def _http_request(qtbot, port, method, path, body=b"", headers=None):
    """Send a raw HTTP/1.1 request and return (status_code, body_bytes).

    Uses signal-driven reads pumped by ``qtbot.waitUntil`` so the shared Qt
    event loop services both the client and the in-process server.
    """
    sock = QTcpSocket()
    received = bytearray()
    done = {"flag": False}

    def _on_ready():
        received.extend(bytes(sock.readAll().data()))

    def _on_disconnected():
        received.extend(bytes(sock.readAll().data()))
        done["flag"] = True

    sock.readyRead.connect(_on_ready)
    sock.disconnected.connect(_on_disconnected)

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

    # The server sends Connection: close, so wait for the full response via
    # disconnection (or at least a complete header block as a fallback).
    qtbot.waitUntil(
        lambda: done["flag"] or b"\r\n\r\n" in bytes(received), timeout=3000
    )
    sock.close()

    head, _, payload = bytes(received).partition(b"\r\n\r\n")
    status_line = head.split(b"\r\n")[0].decode("latin-1")
    status_code = int(status_line.split(" ")[1])
    return status_code, payload


@pytest.fixture
def server(qtbot):
    srv = HttpServer()
    assert srv.start(0, QHostAddress(QHostAddress.SpecialAddress.LocalHost))
    yield srv
    srv.stop()


def test_get_route_returns_json(server, qtbot):
    server.add_route("GET", "/api/state", lambda req: Response.json({"state": "playing"}))
    status, body = _http_request(qtbot, server.port, "GET", "/api/state")
    assert status == 200
    assert json.loads(body) == {"state": "playing"}


def test_post_with_body(server, qtbot):
    seen = {}

    def handler(req: Request) -> Response:
        seen["data"] = req.json()
        return Response.no_content(204)

    server.add_route("POST", "/api/volume", handler)
    status, _ = _http_request(
        qtbot, server.port, "POST", "/api/volume", body=b'{"value": 55}',
        headers={"Content-Type": "application/json"},
    )
    assert status == 204
    assert seen["data"] == {"value": 55}


def test_path_param_captured(server, qtbot):
    captured = {}

    def handler(req: Request) -> Response:
        captured["id"] = req.params.get("id")
        return Response.no_content(204)

    server.add_route("POST", "/api/command/{id}", handler)
    status, _ = _http_request(qtbot, server.port, "POST", "/api/command/next")
    assert status == 204
    assert captured["id"] == "next"


def test_unknown_path_404(server, qtbot):
    status, body = _http_request(qtbot, server.port, "GET", "/nope")
    assert status == 404
    assert "error" in json.loads(body)


def test_method_not_allowed_405(server, qtbot):
    server.add_route("GET", "/api/state", lambda req: Response.json({}))
    status, _ = _http_request(qtbot, server.port, "POST", "/api/state")
    assert status == 405


def test_options_preflight_204(server, qtbot):
    status, _ = _http_request(qtbot, server.port, "OPTIONS", "/api/state")
    assert status == 204


# -- Range header parsing (pure, no Qt) -----------------------------------


def test_parse_range_absent_or_bad():
    assert _parse_range("", 100) is None
    assert _parse_range("bytes=", 100) is None
    assert _parse_range("items=0-10", 100) is None
    assert _parse_range("bytes=abc", 100) is None
    assert _parse_range("bytes=0-10,20-30", 100) is None  # multi-range


def test_parse_range_explicit():
    assert _parse_range("bytes=0-99", 1000) == (0, 99)
    assert _parse_range("bytes=100-199", 1000) == (100, 199)


def test_parse_range_open_ended():
    assert _parse_range("bytes=500-", 1000) == (500, 999)


def test_parse_range_suffix():
    assert _parse_range("bytes=-200", 1000) == (800, 999)
    assert _parse_range("bytes=-5000", 1000) == (0, 999)  # clamp to file


def test_parse_range_clamps_end():
    assert _parse_range("bytes=0-99999", 1000) == (0, 999)


def test_parse_range_unsatisfiable():
    assert _parse_range("bytes=1000-1100", 1000) is None  # start past EOF
    assert _parse_range("bytes=50-10", 1000) is None       # end < start


# -- file serving end-to-end (Range) --------------------------------------


def _http_request_full(qtbot, port, method, path, headers=None):
    """Like _http_request but returns (status, headers_dict, body_bytes)."""
    sock = QTcpSocket()
    received = bytearray()
    done = {"flag": False}

    def _on_ready():
        received.extend(bytes(sock.readAll().data()))

    def _on_disconnected():
        received.extend(bytes(sock.readAll().data()))
        done["flag"] = True

    sock.readyRead.connect(_on_ready)
    sock.disconnected.connect(_on_disconnected)
    sock.connectToHost(QHostAddress(QHostAddress.SpecialAddress.LocalHost), port)
    qtbot.waitUntil(
        lambda: sock.state() == QTcpSocket.SocketState.ConnectedState, timeout=3000
    )
    lines = [f"{method} {path} HTTP/1.1", "Host: localhost"]
    for k, v in (headers or {}).items():
        lines.append(f"{k}: {v}")
    raw = ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")
    sock.write(raw)
    sock.flush()
    qtbot.waitUntil(lambda: done["flag"], timeout=3000)
    sock.close()

    head, _, payload = bytes(received).partition(b"\r\n\r\n")
    head_lines = head.split(b"\r\n")
    status_code = int(head_lines[0].split(b" ")[1])
    hdrs = {}
    for line in head_lines[1:]:
        if b":" in line:
            name, _, value = line.partition(b":")
            hdrs[name.strip().lower().decode("latin-1")] = value.strip().decode("latin-1")
    return status_code, hdrs, payload


@pytest.fixture
def audio_file(tmp_path):
    path = tmp_path / "blob.bin"
    data = bytes(range(256)) * 8  # 2048 deterministic bytes
    path.write_bytes(data)
    return path, data


def test_file_full_body(server, qtbot, audio_file):
    path, data = audio_file
    server.add_route("GET", "/f", lambda req: Response.file(str(path), "audio/mpeg"))
    status, hdrs, body = _http_request_full(qtbot, server.port, "GET", "/f")
    assert status == 200
    assert body == data
    assert hdrs.get("accept-ranges") == "bytes"
    assert hdrs.get("content-length") == str(len(data))
    assert hdrs.get("content-type") == "audio/mpeg"


def test_file_range_partial(server, qtbot, audio_file):
    path, data = audio_file
    server.add_route("GET", "/f", lambda req: Response.file(str(path), "audio/mpeg"))
    status, hdrs, body = _http_request_full(
        qtbot, server.port, "GET", "/f", headers={"Range": "bytes=100-199"}
    )
    assert status == 206
    assert body == data[100:200]
    assert hdrs.get("content-range") == f"bytes 100-199/{len(data)}"
    assert hdrs.get("content-length") == "100"


def test_file_range_open_ended(server, qtbot, audio_file):
    path, data = audio_file
    server.add_route("GET", "/f", lambda req: Response.file(str(path), "audio/mpeg"))
    status, hdrs, body = _http_request_full(
        qtbot, server.port, "GET", "/f", headers={"Range": "bytes=2000-"}
    )
    assert status == 206
    assert body == data[2000:]
    assert hdrs.get("content-range") == f"bytes 2000-{len(data) - 1}/{len(data)}"


def test_file_range_unsatisfiable_416(server, qtbot, audio_file):
    path, data = audio_file
    server.add_route("GET", "/f", lambda req: Response.file(str(path), "audio/mpeg"))
    status, hdrs, _ = _http_request_full(
        qtbot, server.port, "GET", "/f", headers={"Range": "bytes=99999-100000"}
    )
    assert status == 416
    assert hdrs.get("content-range") == f"bytes */{len(data)}"


def test_file_missing_404(server, qtbot, tmp_path):
    missing = tmp_path / "nope.bin"
    server.add_route("GET", "/f", lambda req: Response.file(str(missing), "audio/mpeg"))
    status, _, _ = _http_request_full(qtbot, server.port, "GET", "/f")
    assert status == 404


# -- client aborts mid-stream (no UnconnectedState warnings, server stays up) --


@pytest.fixture
def big_file(tmp_path):
    # Several 64 KiB chunks so _send_file loops and flushes multiple times,
    # giving the client a window to abort mid-stream.
    path = tmp_path / "big.bin"
    data = bytes(range(256)) * (4096)  # ~1 MiB
    path.write_bytes(data)
    return path, data


def test_client_abort_midstream_is_handled(server, qtbot, big_file):
    """If the browser closes the connection partway through a Range stream,
    the server must abandon the write quietly (no exception, no warning
    storm) and keep serving subsequent requests."""
    path, data = big_file
    server.add_route("GET", "/big", lambda req: Response.file(str(path), "audio/mpeg"))

    # Open the stream, read only a little, then slam the socket shut.
    sock = QTcpSocket()
    got = {"n": 0}
    sock.readyRead.connect(lambda: got.__setitem__("n", got["n"] + len(bytes(sock.readAll().data()))))
    sock.connectToHost(QHostAddress(QHostAddress.SpecialAddress.LocalHost), server.port)
    qtbot.waitUntil(
        lambda: sock.state() == QTcpSocket.SocketState.ConnectedState, timeout=3000
    )
    sock.write(b"GET /big HTTP/1.1\r\nHost: localhost\r\n\r\n")
    sock.flush()
    # Wait until at least some bytes have arrived, then abort.
    qtbot.waitUntil(lambda: got["n"] > 0, timeout=3000)
    sock.abort()
    sock.close()

    # Let the server notice the disconnect and unwind its send loop.
    qtbot.wait(100)

    # The server is still healthy: a fresh request succeeds.
    status, _, body = _http_request_full(qtbot, server.port, "GET", "/big")
    assert status == 200
    assert body == data
