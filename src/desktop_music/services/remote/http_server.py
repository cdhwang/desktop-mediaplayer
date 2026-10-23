"""A minimal HTTP/1.1 server built on ``QTcpServer``.

PyQt6 6.11 ships ``QtNetwork`` but *not* ``QtHttpServer``, so this module
implements just enough of HTTP/1.1 to serve a small JSON REST API and the
remote page on the Qt event loop (no extra threads, no external dependencies).

Scope / intentional limitations (this is a trusted-LAN control channel, not a
general web server):

* Only the request line, headers and an optional ``Content-Length`` body are
  parsed. Chunked request bodies are not supported.
* One request per connection is handled, then the socket is closed
  (``Connection: close``). This keeps the parser trivial and is fine for the
  low request volume of a remote control.
* Routing is injected: the owner registers ``(method, path)`` handlers (with
  optional ``{param}`` path segments) that return a :class:`Response`.

The server is transport-only; it knows nothing about the player. The
:class:`~desktop_music.services.remote.remote_service.RemoteService` wires
concrete routes to the controller/playlist.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import parse_qs, unquote, urlsplit

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QHostAddress, QTcpServer, QTcpSocket

# Maximum size we will buffer for a single request (headers + body), to avoid
# unbounded memory use from a misbehaving or malicious client on the LAN.
_MAX_REQUEST_BYTES = 1 * 1024 * 1024  # 1 MiB


@dataclass
class Request:
    """A parsed HTTP request."""

    method: str
    path: str                       # decoded path, no query string
    query: dict[str, str]           # first value per key
    headers: dict[str, str]         # lower-cased header names
    body: bytes
    params: dict[str, str] = field(default_factory=dict)  # matched path params

    def json(self) -> object:
        """Parse the body as JSON, returning ``None`` on empty/invalid body."""
        if not self.body:
            return None
        try:
            return json.loads(self.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None


@dataclass
class Response:
    """An HTTP response to send back."""

    status: int = 200
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def json(cls, data: object, status: int = 200) -> "Response":
        payload = json.dumps(data).encode("utf-8")
        return cls(
            status=status,
            body=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )

    @classmethod
    def no_content(cls, status: int = 204) -> "Response":
        return cls(status=status, body=b"")

    @classmethod
    def error(cls, status: int, message: str) -> "Response":
        return cls.json({"error": message}, status=status)


_STATUS_TEXT = {
    200: "OK",
    204: "No Content",
    400: "Bad Request",
    404: "Not Found",
    405: "Method Not Allowed",
    413: "Payload Too Large",
    500: "Internal Server Error",
}

Handler = Callable[[Request], Response]


class HttpServer(QObject):
    """Lightweight HTTP server. Register routes, then :meth:`start`."""

    # emitted on bind failure with a human-readable reason
    error = pyqtSignal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._server = QTcpServer(self)
        self._server.newConnection.connect(self._on_new_connection)
        # routes: list of (method, segments, handler)
        self._routes: list[tuple[str, list[str], Handler]] = []
        self._port = 0

    # -- routing -----------------------------------------------------------

    def add_route(self, method: str, path: str, handler: Handler) -> None:
        """Register a handler for ``method`` requests to ``path``.

        ``path`` may contain ``{name}`` segments which are captured into
        ``Request.params``. Example: ``/api/command/{id}``.
        """
        self._routes.append((method.upper(), _split_path(path), handler))

    # -- lifecycle ---------------------------------------------------------

    def start(self, port: int, address: Optional[QHostAddress] = None) -> bool:
        """Begin listening on *port* (all interfaces by default).

        Returns True on success; emits :attr:`error` and returns False on
        failure (e.g. the port is already in use).
        """
        addr = address or QHostAddress(QHostAddress.SpecialAddress.Any)
        if not self._server.listen(addr, port):
            self.error.emit(self._server.errorString())
            return False
        self._port = int(self._server.serverPort())
        return True

    def stop(self) -> None:
        if self._server.isListening():
            self._server.close()
        self._port = 0

    @property
    def port(self) -> int:
        return self._port

    def is_listening(self) -> bool:
        return self._server.isListening()

    # -- connection handling ----------------------------------------------

    def _on_new_connection(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                break
            # Buffer per-socket parse state on the object itself.
            socket.setProperty("_buf", b"")
            socket.readyRead.connect(lambda s=socket: self._on_ready_read(s))
            socket.disconnected.connect(socket.deleteLater)

    def _on_ready_read(self, socket: QTcpSocket) -> None:
        chunk = bytes(socket.readAll().data())
        buf = socket.property("_buf") or b""
        buf += chunk
        if len(buf) > _MAX_REQUEST_BYTES:
            self._send(socket, Response.error(413, "request too large"))
            return
        socket.setProperty("_buf", buf)

        # Need the full header block before we can decide on body length.
        header_end = buf.find(b"\r\n\r\n")
        if header_end == -1:
            return  # wait for more data

        head = buf[:header_end].decode("latin-1", "replace")
        body_start = header_end + 4
        lines = head.split("\r\n")
        if not lines:
            self._send(socket, Response.error(400, "malformed request"))
            return

        request_line = lines[0]
        parts = request_line.split(" ")
        if len(parts) < 2:
            self._send(socket, Response.error(400, "malformed request line"))
            return
        method = parts[0].upper()
        target = parts[1]

        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" in line:
                name, _, value = line.partition(":")
                headers[name.strip().lower()] = value.strip()

        # Wait for the full body if Content-Length says there is more.
        content_length = 0
        if "content-length" in headers:
            try:
                content_length = int(headers["content-length"])
            except ValueError:
                content_length = 0
        available = len(buf) - body_start
        if available < content_length:
            return  # wait for the rest of the body
        body = buf[body_start:body_start + content_length]

        split = urlsplit(target)
        path = unquote(split.path)
        query = {k: v[0] for k, v in parse_qs(split.query).items()}

        request = Request(
            method=method,
            path=path,
            query=query,
            headers=headers,
            body=body,
        )
        response = self._dispatch(request)
        self._send(socket, response)

    def _dispatch(self, request: Request) -> Response:
        # CORS preflight: allow everything (trusted LAN, no auth).
        if request.method == "OPTIONS":
            return Response.no_content(204)

        segments = _split_path(request.path)
        path_matched = False
        for method, route_segments, handler in self._routes:
            params = _match(route_segments, segments)
            if params is None:
                continue
            path_matched = True
            if method != request.method:
                continue
            request.params = params
            try:
                return handler(request)
            except Exception as exc:  # noqa: BLE001 - never crash the server
                return Response.error(500, f"handler error: {exc}")

        if path_matched:
            return Response.error(405, "method not allowed")
        return Response.error(404, "not found")

    def _send(self, socket: QTcpSocket, response: Response) -> None:
        text = _STATUS_TEXT.get(response.status, "OK")
        headers = dict(response.headers)
        headers.setdefault("Content-Length", str(len(response.body)))
        # Permissive CORS for a trusted-LAN control channel.
        headers.setdefault("Access-Control-Allow-Origin", "*")
        headers.setdefault("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        headers.setdefault("Access-Control-Allow-Headers", "Content-Type")
        headers.setdefault("Connection", "close")

        out = [f"HTTP/1.1 {response.status} {text}"]
        out += [f"{k}: {v}" for k, v in headers.items()]
        raw = ("\r\n".join(out) + "\r\n\r\n").encode("latin-1") + response.body
        try:
            socket.write(raw)
            socket.flush()
            socket.disconnectFromHost()
        except RuntimeError:
            # socket may already be gone; ignore
            pass


def _split_path(path: str) -> list[str]:
    """Split a URL path into non-empty segments."""
    return [seg for seg in path.split("/") if seg != ""]


def _match(route_segments: list[str], segments: list[str]) -> Optional[dict[str, str]]:
    """Match a request path against a route template.

    Returns the captured ``{param}`` values on a match, or ``None`` when the
    paths do not match.
    """
    if len(route_segments) != len(segments):
        return None
    params: dict[str, str] = {}
    for tmpl, actual in zip(route_segments, segments):
        if tmpl.startswith("{") and tmpl.endswith("}"):
            params[tmpl[1:-1]] = actual
        elif tmpl != actual:
            return None
    return params
