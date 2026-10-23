"""RemoteService: exposes the player on the LAN over plain HTTP.

This is the single object the desktop app creates to let a web browser on the
same Wi-Fi control playback. It owns a lightweight HTTP server that serves:

* a small JSON REST API (commands + state/playlist reads), and
* a single self-contained HTML remote-control page at ``/``.

The browser page polls ``/api/state`` and ``/api/playlist`` on a timer to
stay current -- there is no WebSocket channel and no discovery; the user
points the browser at ``http://<desktop-ip>:8787/``.

Design notes:

* The service runs entirely on the Qt GUI thread, the same thread as the
  :class:`PlayerController` and :class:`PlaylistModel`, so route handlers can
  call controller/model methods directly without locking.
* Handlers are thin: validate input, call one controller/model method, and
  return the fresh state snapshot so a polling client can update immediately.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QObject
from PyQt6.QtNetwork import QHostAddress

from desktop_music.services.remote import state as rstate
from desktop_music.services.remote.http_server import HttpServer, Request, Response
from desktop_music.services.remote.web import REMOTE_PAGE_HTML

# Command ids accepted by POST /api/command/{id}. These map onto
# PlayerController.dispatch, which already knows the core command set.
_DISPATCH_COMMANDS = {
    "play_pause",
    "stop",
    "next",
    "previous",
    "seek_forward",
    "seek_backward",
    "seek_forward_long",
    "seek_backward_long",
    "volume_up",
    "volume_down",
    "mute",
    "toggle_shuffle",
    "cycle_repeat",
    "rate_up",
    "rate_down",
    "rate_reset",
}

# Default HTTP port. The browser connects to http://<desktop-ip>:<port>/.
DEFAULT_HTTP_PORT = 8787


class RemoteService(QObject):
    """Owns the HTTP surface (REST API + remote page) and binds it to the player."""

    def __init__(
        self,
        controller,
        playlist,
        *,
        http_port: int = DEFAULT_HTTP_PORT,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._playlist = playlist
        self._http_port = http_port
        self._http = HttpServer(self)
        self._register_routes()

    # -- lifecycle ---------------------------------------------------------

    def start(self, address: Optional[QHostAddress] = None) -> bool:
        """Start the HTTP server. Returns True on success."""
        return self._http.start(self._http_port, address)

    def stop(self) -> None:
        self._http.stop()

    @property
    def http(self) -> HttpServer:
        return self._http

    @property
    def http_port(self) -> int:
        return self._http.port or self._http_port

    # -- routes ------------------------------------------------------------

    def _register_routes(self) -> None:
        add = self._http.add_route
        # Remote-control web page (served at both / and /remote).
        add("GET", "/", self._h_page)
        add("GET", "/remote", self._h_page)
        # JSON API.
        add("GET", "/api/ping", self._h_ping)
        add("GET", "/api/state", self._h_state)
        add("GET", "/api/playlist", self._h_playlist)
        add("GET", "/api/cover/{index}", self._h_cover)
        add("GET", "/api/audio/{index}", self._h_audio)
        add("POST", "/api/command/{id}", self._h_command)
        add("POST", "/api/volume", self._h_volume)
        add("POST", "/api/seek", self._h_seek)
        add("POST", "/api/play", self._h_play)
        add("POST", "/api/remove", self._h_remove)
        # Browser -> desktop: the web player reports its own playback position
        # and state so the desktop UI can mirror it in remote mode.
        add("POST", "/api/remote/state", self._h_remote_state)

    # -- handlers ----------------------------------------------------------

    def _h_page(self, _req: Request) -> Response:
        return Response(
            status=200,
            body=REMOTE_PAGE_HTML.encode("utf-8"),
            headers={"Content-Type": "text/html; charset=utf-8"},
        )

    def _h_ping(self, _req: Request) -> Response:
        return Response.json({"ok": True, "app": "desktop-music"})

    def _h_state(self, _req: Request) -> Response:
        snap = rstate.build_state_snapshot(self._controller, self._playlist)
        return Response.json(snap)

    def _h_playlist(self, _req: Request) -> Response:
        return Response.json(rstate.build_playlist(self._playlist))

    def _h_cover(self, req: Request) -> Response:
        """Serve the album art for a playlist track as a raw image.

        ``GET /api/cover/{index}`` returns the cover-art bytes for the track
        at *index* with the sniffed image Content-Type, or 404 when the track
        has no art. The response is marked ``no-store`` so the browser never
        reuses a stale cover for an index whose track has changed (e.g. the
        playlist was reordered or trimmed).
        """
        raw_index = req.params.get("index", "")
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            return Response.error(400, "index must be an integer")
        track = (
            self._playlist.track_at(index)
            if self._playlist is not None and hasattr(self._playlist, "track_at")
            else None
        )
        if track is None:
            return Response.error(404, "track not found")
        cover = rstate.track_cover_bytes(track)
        if cover is None:
            return Response.error(404, "no cover art")
        data, content_type = cover
        return Response(
            status=200,
            body=data,
            headers={
                "Content-Type": content_type,
                "Cache-Control": "no-store, no-cache, must-revalidate",
            },
        )

    def _h_audio(self, req: Request) -> Response:
        """Stream a playlist track to the browser as MP3.

        ``GET /api/audio/{index}`` transcodes the track at *index* to MP3
        (reusing a cached copy when available) and serves the resulting file
        with HTTP Range support, so the browser ``<audio>`` element can seek
        and show an accurate duration. Cue-sheet tracks are limited to their
        segment via the track's ``start_ms``/``end_ms``.

        The transcode runs synchronously on the GUI thread. For a typical
        song this takes a few seconds on first request; subsequent requests
        (including the browser's own Range follow-ups) hit the cache and
        return immediately.
        """
        raw_index = req.params.get("index", "")
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            return Response.error(400, "index must be an integer")
        track = (
            self._playlist.track_at(index)
            if self._playlist is not None and hasattr(self._playlist, "track_at")
            else None
        )
        if track is None:
            return Response.error(404, "track not found")
        path = getattr(track, "path", "") or ""
        if not path:
            return Response.error(404, "track has no source file")

        # Imported lazily so the (ffmpeg-dependent) transcode stack is only
        # pulled in when a browser actually requests audio.
        from desktop_music.services.remote.transcode import (
            TranscodeError,
            transcode_to_mp3,
        )

        start_ms = int(getattr(track, "start_ms", 0) or 0)
        end_ms = int(getattr(track, "end_ms", 0) or 0)
        try:
            mp3_path = transcode_to_mp3(path, start_ms, end_ms)
        except TranscodeError as exc:
            # 503: the source exists but we couldn't produce playable audio
            # right now (ffmpeg missing or decode failure).
            return Response.error(503, f"transcode failed: {exc}")
        return Response.file(
            str(mp3_path),
            "audio/mpeg",
            headers={"Cache-Control": "no-store"},
        )

    def _h_command(self, req: Request) -> Response:
        command_id = req.params.get("id", "")
        if command_id not in _DISPATCH_COMMANDS:
            return Response.error(400, f"unknown command: {command_id}")
        self._controller.dispatch(command_id)
        return Response.json(self._ack())

    def _h_volume(self, req: Request) -> Response:
        data = req.json()
        if not isinstance(data, dict) or "value" not in data:
            return Response.error(400, "expected JSON {\"value\": 0..100}")
        try:
            value = int(data["value"])
        except (TypeError, ValueError):
            return Response.error(400, "value must be an integer")
        if not 0 <= value <= 100:
            return Response.error(400, "value out of range (0..100)")
        self._controller.set_volume(value)
        return Response.json(self._ack())

    def _h_seek(self, req: Request) -> Response:
        data = req.json()
        if not isinstance(data, dict):
            return Response.error(400, "expected JSON body")
        if "fraction" in data:
            try:
                fraction = float(data["fraction"])
            except (TypeError, ValueError):
                return Response.error(400, "fraction must be a number")
            fraction = max(0.0, min(1.0, fraction))
            self._controller.seek_to_fraction(fraction)
            return Response.json(self._ack())
        if "ms" in data:
            try:
                ms = int(data["ms"])
            except (TypeError, ValueError):
                return Response.error(400, "ms must be an integer")
            self._controller.seek_to_ms(max(0, ms))
            return Response.json(self._ack())
        return Response.error(400, "expected 'fraction' (0..1) or 'ms'")

    def _h_play(self, req: Request) -> Response:
        data = req.json()
        if not isinstance(data, dict) or "index" not in data:
            return Response.error(400, "expected JSON {\"index\": int}")
        try:
            index = int(data["index"])
        except (TypeError, ValueError):
            return Response.error(400, "index must be an integer")
        count = self._playlist.rowCount() if self._playlist is not None else 0
        if not 0 <= index < count:
            return Response.error(400, f"index out of range (0..{count - 1})")
        self._controller.play_row(index)
        return Response.json(self._ack())

    def _h_remove(self, req: Request) -> Response:
        """Remove a playlist track (keeps desktop and browser in sync).

        Body: ``{"index": int}``. Removes the track at *index* from the
        shared playlist model via ``remove_row``, which also advances the
        now-playing cursor to the next track when the current one is removed.
        Both clients converge because the browser polls the playlist and the
        desktop UI is driven by the same model.
        """
        data = req.json()
        if not isinstance(data, dict) or "index" not in data:
            return Response.error(400, "expected JSON {\"index\": int}")
        try:
            index = int(data["index"])
        except (TypeError, ValueError):
            return Response.error(400, "index must be an integer")
        count = self._playlist.rowCount() if self._playlist is not None else 0
        if not 0 <= index < count:
            return Response.error(400, f"index out of range (0..{count - 1})")
        self._playlist.remove_row(index)
        return Response.json(self._ack())

    def _h_remote_state(self, req: Request) -> Response:
        """Ingest the browser's playback position/state (reverse sync).

        Body: ``{"position_ms": int, "length_ms": int, "state": str}``. The
        desktop uses this to mirror the browser's progress in remote mode. A
        no-op when the controller doesn't support remote reporting.
        """
        data = req.json()
        if not isinstance(data, dict):
            return Response.error(400, "expected JSON body")
        try:
            position_ms = int(data.get("position_ms", 0))
            length_ms = int(data.get("length_ms", 0))
        except (TypeError, ValueError):
            return Response.error(400, "position_ms/length_ms must be integers")
        state = str(data.get("state", ""))
        if hasattr(self._controller, "set_remote_report"):
            self._controller.set_remote_report(
                position_ms=position_ms, length_ms=length_ms, state=state
            )
        return Response.json(self._ack())

    # -- helpers -----------------------------------------------------------

    def _ack(self) -> dict:
        """Echo the fresh state snapshot so a polling client updates at once."""
        return rstate.build_state_snapshot(self._controller, self._playlist)
