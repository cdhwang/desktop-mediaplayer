"""Serialization of player state into plain dicts for the remote API.

These helpers are deliberately Qt-agnostic: they only read attributes and
call methods that already exist on :class:`PlayerController`,
:class:`PlaylistModel` and the VLC backend. Keeping them as free functions
(rather than methods on the controller) makes them trivial to unit test with
lightweight fakes and keeps the remote concern out of the core classes.

The JSON shapes produced here are the contract the Android client depends
on, so they are documented inline.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

_log = logging.getLogger("desktop_music.remote.state")

# These imports are only used for isinstance-free value normalization and to
# avoid a hard dependency cycle; the functions accept duck-typed objects.


def _track_has_cover(track: Any) -> bool:
    """Best-effort check for whether *track* can provide cover art.

    This is intentionally cheap: it only checks that the backing file exists
    and is a readable path. The actual (more expensive) extraction happens
    lazily when the browser requests ``/api/cover/{index}``.
    """
    if track is None:
        return False
    path = getattr(track, "path", "") or ""
    return bool(path) and os.path.isfile(path)


def track_cover_bytes(track: Any) -> Optional[tuple[bytes, str]]:
    """Extract cover-art bytes + content-type for *track*.

    Returns ``(data, content_type)`` or ``None`` when no art is available.
    The content type is sniffed from the leading image magic bytes so the
    browser can render it without a separate type tag.
    """
    if track is None:
        return None
    path = getattr(track, "path", "") or ""
    if not path or not os.path.isfile(path):
        return None

    # Imported lazily to keep this module free of a hard mutagen dependency
    # at import time and to avoid a service<->service import cycle.
    from desktop_music.services.metadata import read_metadata

    meta = read_metadata(path)
    data = getattr(meta, "cover_art", None)
    if not data:
        return None
    return bytes(data), _sniff_image_type(bytes(data))


def _sniff_image_type(data: bytes) -> str:
    """Return an image MIME type guessed from *data*'s magic bytes."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:2] == b"BM":
        return "image/bmp"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def _enum_value(obj: Any, default: str = "") -> str:
    """Return ``obj.value`` when *obj* looks like an enum member, else str."""
    value = getattr(obj, "value", None)
    if isinstance(value, str):
        return value
    if obj is None:
        return default
    return str(obj)


def _track_title(track: Any) -> str:
    """Best-effort display title for a track-like object."""
    if track is None:
        return ""
    display = getattr(track, "display_title", None)
    if display:
        return str(display)
    title = getattr(track, "title", "") or ""
    if title:
        return str(title)
    path = getattr(track, "path", "") or ""
    return os.path.basename(path)


def build_track(track: Any, index: int, *, playing: bool) -> dict[str, Any]:
    """Serialize one playlist track into a dict.

    Shape::

        {
          "index": int,
          "title": str,          # artist - title, or file name fallback
          "raw_title": str,      # tag title only (may be empty)
          "artist": str,
          "duration_ms": int,
          "playing": bool,       # True for the current (now-playing) row
          "is_cue_track": bool,
          "has_cover": bool,     # True when album art is available
        }
    """
    return {
        "index": index,
        "title": _track_title(track),
        "raw_title": str(getattr(track, "title", "") or ""),
        "artist": str(getattr(track, "artist", "") or ""),
        "duration_ms": int(getattr(track, "duration_ms", 0) or 0),
        "playing": bool(playing),
        "is_cue_track": bool(getattr(track, "is_cue_track", False)),
        "has_cover": _track_has_cover(track),
    }


def build_playlist(playlist: Any) -> dict[str, Any]:
    """Serialize the whole playlist.

    Shape::

        {
          "count": int,
          "current_index": int,       # -1 when nothing is current
          "tracks": [ <build_track>, ... ],
        }
    """
    if playlist is None:
        return {"count": 0, "current_index": -1, "tracks": []}

    current = int(getattr(playlist, "current_index", -1))
    count = int(playlist.rowCount()) if hasattr(playlist, "rowCount") else 0
    tracks: list[dict[str, Any]] = []
    for i in range(count):
        track = playlist.track_at(i) if hasattr(playlist, "track_at") else None
        tracks.append(build_track(track, i, playing=(i == current)))
    return {"count": count, "current_index": current, "tracks": tracks}


def build_state_snapshot(controller: Any, playlist: Any | None = None) -> dict[str, Any]:
    """Serialize the live playback state into a dict.

    *playlist* defaults to ``controller.playlist`` when omitted. The current
    track metadata is embedded so a client can render "now playing" from a
    single ``/api/state`` call without also fetching the playlist.

    Shape::

        {
          "state": str,            # PlaybackState value: playing/paused/...
          "position_ms": int,
          "length_ms": int,
          "volume": int,           # 0..100
          "muted": bool,
          "shuffle": bool,
          "repeat": str,           # none/all/one
          "rate": float,
          "current_index": int,    # -1 when nothing is current
          "current": <build_track> | null,
        }
    """
    if playlist is None:
        playlist = getattr(controller, "playlist", None)

    backend = getattr(controller, "backend", None)

    # Playback state (normalized enum value string).
    state = ""
    if backend is not None and hasattr(backend, "get_state"):
        state = _enum_value(backend.get_state())

    # Position / length in ms. Prefer the backend's live values; clamp the
    # sentinel -1 that libVLC returns when nothing is loaded.
    position_ms = 0
    length_ms = 0
    if backend is not None:
        try:
            position_ms = max(0, int(backend.get_time()))
        except (TypeError, ValueError):
            position_ms = 0
        try:
            length_ms = max(0, int(backend.get_length()))
        except (TypeError, ValueError):
            length_ms = 0

    # Volume / mute. The controller tracks the requested volume (avoids
    # libVLC's read-back lag); mute comes from the backend.
    try:
        volume = int(getattr(controller, "volume", 100))
    except (TypeError, ValueError):
        volume = 100
    muted = False
    if backend is not None and hasattr(backend, "is_muted"):
        muted = bool(backend.is_muted())

    # Play mode (shuffle / repeat).
    play_mode = getattr(controller, "play_mode", None)
    shuffle = bool(getattr(play_mode, "shuffle", False))
    repeat = _enum_value(getattr(play_mode, "repeat", None), default="none")

    # Playback rate.
    rate = 1.0
    if backend is not None and hasattr(backend, "get_rate"):
        try:
            rate = float(backend.get_rate())
        except (TypeError, ValueError):
            rate = 1.0

    # Current track metadata.
    current_index = int(getattr(playlist, "current_index", -1)) if playlist else -1
    current_track = None
    if playlist is not None and hasattr(playlist, "current_track"):
        current_track = playlist.current_track()
    current = (
        build_track(current_track, current_index, playing=True)
        if current_track is not None
        else None
    )

    # Remote (browser-playback) mode: the browser is the source of truth for
    # the live playback position/state, so prefer its last report over the
    # desktop backend (which is paused at position 0 while muted). Volume,
    # mute, shuffle/repeat and track metadata still come from the desktop.
    remote_report = getattr(controller, "remote_report", None)
    remote_mode = bool(getattr(controller, "remote_mode", False))
    if remote_mode and isinstance(remote_report, dict):
        position_ms = int(remote_report.get("position_ms", position_ms))
        length_ms = int(remote_report.get("length_ms", length_ms))
        reported_state = remote_report.get("state")
        if reported_state:
            state = str(reported_state)

    snapshot = {
        "state": state,
        "position_ms": position_ms,
        "length_ms": length_ms,
        "volume": volume,
        "muted": muted,
        "shuffle": shuffle,
        "repeat": repeat,
        "rate": rate,
        "current_index": current_index,
        "current": current,
        "remote_mode": remote_mode,
    }
    _log.debug(
        "snapshot: remote_mode=%s muted=%s state=%s pos=%s len=%s idx=%s "
        "has_report=%s",
        remote_mode, muted, state, position_ms, length_ms, current_index,
        isinstance(remote_report, dict),
    )
    return snapshot
