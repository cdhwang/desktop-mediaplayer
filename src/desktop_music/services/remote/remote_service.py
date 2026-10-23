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

import logging
import time
import uuid

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, QTimer
from PyQt6.QtNetwork import QHostAddress

from desktop_music.services.remote import state as rstate
from desktop_music.services.remote.http_server import HttpServer, Request, Response
from desktop_music.services.remote.web import REMOTE_PAGE_HTML

_log = logging.getLogger("desktop_music.remote")

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

# How long (seconds) an audio claim survives without a heartbeat. The holder
# refreshes its claim on every remote-state report (roughly once a second),
# so a claim that goes silent for this long is treated as abandoned -- the
# desktop reclaims its own audio and another client may claim it.
_CLAIM_TIMEOUT_S = 6.0

# How often (ms) the service checks the active claim for expiry. Kept short
# relative to the timeout so the desktop recovers audio promptly when the
# holding browser is closed or loses connectivity.
_CLAIM_SWEEP_MS = 2000


class _TranscodeJob(QRunnable):
    """Runs one transcode off the GUI thread and sends the HTTP response.

    The actual ffmpeg call (``transcode_to_mp3``) blocks, so it runs on a
    :class:`QThreadPool` worker instead of the GUI/event thread. Only pure
    data (paths, ints) crosses the boundary; the response is delivered back
    on the GUI thread via ``req.respond_later`` (a queued signal), which is
    the only place the socket is touched.
    """

    def __init__(self, req: Request, path: str, start_ms: int, end_ms: int) -> None:
        super().__init__()
        self._req = req
        self._path = path
        self._start_ms = start_ms
        self._end_ms = end_ms

    def run(self) -> None:  # executed on a worker thread
        # Imported lazily so the (ffmpeg-dependent) transcode stack is only
        # pulled in when a browser actually requests audio.
        from desktop_music.services.remote.transcode import (
            TranscodeError,
            transcode_to_mp3,
        )

        try:
            mp3_path = transcode_to_mp3(self._path, self._start_ms, self._end_ms)
        except TranscodeError as exc:
            # 503: the source exists but we couldn't produce playable audio
            # right now (ffmpeg missing or decode failure).
            self._req.respond_later(
                Response.error(503, f"transcode failed: {exc}")
            )
            return
        except Exception as exc:  # noqa: BLE001 - never kill the worker thread
            self._req.respond_later(
                Response.error(500, f"transcode error: {exc}")
            )
            return
        self._req.respond_later(
            Response.file(
                str(mp3_path),
                "audio/mpeg",
                headers={"Cache-Control": "no-store"},
            )
        )


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

        # Dedicated pool for blocking transcode jobs so they never run on the
        # GUI/event thread (which also owns the socket). Bounded so a flood of
        # audio requests can't spawn unbounded ffmpeg processes.
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)

        # Audio-claim state. The desktop keeps its own audio by default; it
        # only hands audio to the browser (controller.set_remote_mode(True))
        # when a client *explicitly* claims it, and only one client may hold
        # the claim at a time. ``_claim_token`` identifies the holder;
        # ``_claim_seen`` is the monotonic timestamp of its last heartbeat.
        self._claim_token: Optional[str] = None
        self._claim_seen: float = 0.0

        # Periodically expire a claim whose holder stopped sending heartbeats
        # (e.g. the browser tab was closed), so the desktop reclaims audio.
        self._claim_timer = QTimer(self)
        self._claim_timer.setInterval(_CLAIM_SWEEP_MS)
        self._claim_timer.timeout.connect(self._expire_stale_claim)

        self._register_routes()

    # -- lifecycle ---------------------------------------------------------

    def start(self, address: Optional[QHostAddress] = None) -> bool:
        """Start the HTTP server. Returns True on success."""
        ok = self._http.start(self._http_port, address)
        if ok:
            self._claim_timer.start()
        return ok

    def stop(self) -> None:
        self._claim_timer.stop()
        # Wait for in-flight transcode workers to finish so their deferred
        # responses don't fire against a torn-down HTTP server. Bounded wait
        # so shutdown can't hang forever on a stuck ffmpeg.
        self._pool.clear()  # drop queued-but-not-started jobs
        self._pool.waitForDone(5000)
        # Release any outstanding claim so the desktop regains its audio when
        # the remote feature is turned off.
        self._release_claim()
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
        # Browser -> desktop: explicitly claim/release the desktop audio so
        # the browser becomes the sole audio source. Only one claim at a time.
        add("POST", "/api/audio/claim", self._h_audio_claim)
        add("POST", "/api/audio/release", self._h_audio_release)

    # -- handlers ----------------------------------------------------------

    def _h_page(self, _req: Request) -> Response:
        return Response(
            status=200,
            body=REMOTE_PAGE_HTML.encode("utf-8"),
            headers={
                "Content-Type": "text/html; charset=utf-8",
                # The page is a single inline HTML+JS blob that changes with
                # app updates; never let the browser serve a stale copy, or
                # fixes to the remote UI won't take effect until a hard reload.
                "Cache-Control": "no-store, no-cache, must-revalidate",
            },
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

        The transcode blocks (it shells out to ffmpeg), so it is handed to a
        background :class:`QThreadPool` worker and the response is deferred:
        the GUI thread stays responsive while a first-time track converts.
        A cache hit still runs on the worker but returns almost immediately.
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

        start_ms = int(getattr(track, "start_ms", 0) or 0)
        end_ms = int(getattr(track, "end_ms", 0) or 0)

        # If the request can't be deferred (e.g. a unit-constructed Request
        # with no responder), fall back to running inline so behaviour is
        # still correct outside the live server.
        if req.responder is None:
            from desktop_music.services.remote.transcode import (
                TranscodeError,
                transcode_to_mp3,
            )

            try:
                mp3_path = transcode_to_mp3(path, start_ms, end_ms)
            except TranscodeError as exc:
                return Response.error(503, f"transcode failed: {exc}")
            return Response.file(
                str(mp3_path), "audio/mpeg", headers={"Cache-Control": "no-store"}
            )

        # Hand off to a worker thread and defer the response.
        self._pool.start(_TranscodeJob(req, path, start_ms, end_ms))
        return Response.defer()

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

        Body: ``{"position_ms": int, "length_ms": int, "state": str,
        "token": str}``. The desktop uses this to mirror the browser's
        progress in remote mode, and it doubles as the heartbeat for the
        audio claim: only the client currently holding the claim (matching
        ``token``) refreshes it, and only its report is mirrored. A no-op
        when the controller doesn't support remote reporting.
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
        token = str(data.get("token", "")) or None
        # Only the current claim holder's report counts. If no one holds the
        # claim, the browser is not the audio source, so ignore the report.
        if token is None or token != self._claim_token:
            return Response.json(self._ack())
        # Refresh the heartbeat for the holder.
        self._claim_seen = time.monotonic()
        if hasattr(self._controller, "set_remote_report"):
            self._controller.set_remote_report(
                position_ms=position_ms, length_ms=length_ms, state=state
            )
        return Response.json(self._ack())

    # -- audio claim -------------------------------------------------------

    def _h_audio_claim(self, req: Request) -> Response:
        """Claim the desktop audio for the calling browser (single holder).

        Body: optional ``{"token": str}``. If the caller passes the token it
        already holds, the claim is simply refreshed. Otherwise a new claim
        is granted only when no other client currently holds one; a live
        foreign claim yields ``409 Conflict`` so a second browser cannot
        steal audio from the first.

        On a successful (new or refreshed) claim the desktop switches to
        browser-playback mode (muted, load-only) via
        ``controller.set_remote_mode(True)``.
        """
        data = req.json()
        if data is not None and not isinstance(data, dict):
            return Response.error(400, "expected JSON body")
        req_token = str((data or {}).get("token", "")) or None

        # Drop a claim that has gone silent before deciding.
        self._expire_stale_claim()

        if self._claim_token is not None and req_token != self._claim_token:
            # Someone else holds a live claim.
            _log.info(
                "claim DENIED (409): req_token=%s holder=%s",
                req_token, self._claim_token,
            )
            return Response.error(409, "audio already claimed by another client")

        if self._claim_token is None:
            self._claim_token = req_token or uuid.uuid4().hex
        self._claim_seen = time.monotonic()

        # Capture where the desktop is *before* entering remote mode (which
        # pauses the backend), so the browser can resume from that point
        # instead of restarting at 0. resume_ms is relative to the current
        # (cue) segment, matching the per-track MP3 the browser streams.
        resume_ms = 0
        was_playing = False
        ctrl = self._controller
        if hasattr(ctrl, "current_relative_position_ms"):
            try:
                resume_ms = int(ctrl.current_relative_position_ms())
            except Exception:  # noqa: BLE001
                resume_ms = 0
        backend = getattr(ctrl, "backend", None)
        if backend is not None and hasattr(backend, "is_playing"):
            try:
                was_playing = bool(backend.is_playing())
            except Exception:  # noqa: BLE001
                was_playing = False

        self._set_remote_mode(True)

        snap = self._ack()
        snap["audio_token"] = self._claim_token
        snap["resume_ms"] = max(0, resume_ms)
        snap["resume_playing"] = was_playing
        _log.info(
            "claim GRANTED token=%s -> remote_mode=%s muted=%s resume_ms=%s "
            "resume_playing=%s len=%s state=%s",
            self._claim_token, snap.get("remote_mode"), snap.get("muted"),
            snap.get("resume_ms"), snap.get("resume_playing"),
            snap.get("length_ms"), snap.get("state"),
        )
        return Response.json(snap)

    def _h_audio_release(self, req: Request) -> Response:
        """Release the audio claim held by the calling browser.

        Body: optional ``{"token": str}``. The claim is released only when
        the token matches the current holder (or no token is given, which is
        treated as a best-effort release of the caller's own claim). Releasing
        restores normal desktop playback. Idempotent / always 200.
        """
        data = req.json()
        if data is not None and not isinstance(data, dict):
            return Response.error(400, "expected JSON body")
        req_token = str((data or {}).get("token", "")) or None
        if (
            self._claim_token is not None
            and req_token is not None
            and req_token != self._claim_token
        ):
            # Not the holder: refuse to release someone else's claim, but do
            # not error -- the caller simply doesn't own audio.
            _log.info(
                "release IGNORED: req_token=%s is not holder=%s",
                req_token, self._claim_token,
            )
            snap = self._ack()
            snap["audio_token"] = None
            return Response.json(snap)
        self._release_claim()
        snap = self._ack()
        snap["audio_token"] = None
        _log.info(
            "release DONE req_token=%s -> remote_mode=%s muted=%s pos=%s len=%s state=%s",
            req_token, snap.get("remote_mode"), snap.get("muted"),
            snap.get("position_ms"), snap.get("length_ms"), snap.get("state"),
        )
        return Response.json(snap)

    def _release_claim(self) -> None:
        """Drop any active claim and return audio to the desktop."""
        if self._claim_token is None:
            return
        _log.info("_release_claim: dropping token=%s", self._claim_token)
        self._claim_token = None
        self._claim_seen = 0.0
        self._set_remote_mode(False)

    def _expire_stale_claim(self) -> None:
        """Release the claim if its holder stopped sending heartbeats."""
        if self._claim_token is None:
            return
        silent = time.monotonic() - self._claim_seen
        if silent > _CLAIM_TIMEOUT_S:
            _log.info(
                "claim EXPIRED token=%s (silent %.1fs > %.1fs)",
                self._claim_token, silent, _CLAIM_TIMEOUT_S,
            )
            self._release_claim()

    def _set_remote_mode(self, enabled: bool) -> None:
        if hasattr(self._controller, "set_remote_mode"):
            before = bool(getattr(self._controller, "remote_mode", False))
            self._controller.set_remote_mode(enabled)
            after = bool(getattr(self._controller, "remote_mode", False))
            _log.info(
                "set_remote_mode(%s): controller.remote_mode %s -> %s",
                enabled, before, after,
            )

    # -- helpers -----------------------------------------------------------

    def _ack(self) -> dict:
        """Echo the fresh state snapshot so a polling client updates at once."""
        return rstate.build_state_snapshot(self._controller, self._playlist)
