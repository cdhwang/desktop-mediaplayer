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
