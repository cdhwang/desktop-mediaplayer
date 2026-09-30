"""Thin wrapper around python-vlc (libVLC).

This module is intentionally free of any Qt dependency so it can be unit
tested in isolation and mocked easily by higher layers. The UI-facing
:class:`PlayerController` (Task 3) adapts this backend to Qt signals.
"""

from __future__ import annotations

import enum
from typing import Optional

import vlc


class PlaybackState(enum.Enum):
    """Normalized playback state, decoupled from vlc.State internals."""

    IDLE = "idle"
    OPENING = "opening"
    BUFFERING = "buffering"
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"
    ENDED = "ended"
    ERROR = "error"


_VLC_STATE_MAP = {
    vlc.State.NothingSpecial: PlaybackState.IDLE,
    vlc.State.Opening: PlaybackState.OPENING,
    vlc.State.Buffering: PlaybackState.BUFFERING,
    vlc.State.Playing: PlaybackState.PLAYING,
    vlc.State.Paused: PlaybackState.PAUSED,
    vlc.State.Stopped: PlaybackState.STOPPED,
    vlc.State.Ended: PlaybackState.ENDED,
    vlc.State.Error: PlaybackState.ERROR,
}


class VLCBackend:
    """Wraps a libVLC ``Instance`` and ``MediaPlayer``.

    Time values are handled in milliseconds (libVLC's native unit).
    Volume is an integer percentage in the range 0..100 (clamped).
    """

    def __init__(self) -> None:
        # --no-xlib avoids threading issues; video output window is set later.
        self._instance: vlc.Instance = vlc.Instance()
        self._player: vlc.MediaPlayer = self._instance.media_player_new()
        self._current_path: Optional[str] = None

    # -- media loading -----------------------------------------------------

    def load(self, path: str) -> None:
        """Load a media file (does not start playback)."""
        media = self._instance.media_new(path)
        self._player.set_media(media)
        self._current_path = path

    @property
    def current_path(self) -> Optional[str]:
        return self._current_path

    # -- transport ---------------------------------------------------------

    def play(self) -> None:
        self._player.play()

    def pause(self) -> None:
        """Pause playback if currently playing (no-op otherwise)."""
        if self._player.is_playing():
            self._player.pause()

    def toggle_pause(self) -> None:
        """Toggle between play and pause."""
        self._player.pause()

    def stop(self) -> None:
        self._player.stop()

    # -- seeking / position ------------------------------------------------

    def seek(self, ms: int) -> None:
        """Seek to an absolute position in milliseconds."""
        self._player.set_time(max(0, int(ms)))

    def get_time(self) -> int:
        """Current position in milliseconds (-1 if unavailable)."""
        return int(self._player.get_time())

    def get_length(self) -> int:
        """Total media length in milliseconds (0 if unknown)."""
        return max(0, int(self._player.get_length()))

    def get_position(self) -> float:
        """Playback position as a fraction 0.0..1.0."""
        return float(self._player.get_position())

    def set_position(self, fraction: float) -> None:
        """Seek to a fractional position 0.0..1.0."""
        self._player.set_position(_clamp(fraction, 0.0, 1.0))

    # -- volume ------------------------------------------------------------

    def set_volume(self, volume: int) -> None:
        """Set output volume as a percentage 0..100."""
        self._player.audio_set_volume(int(_clamp(volume, 0, 100)))

    def get_volume(self) -> int:
        return int(self._player.audio_get_volume())

    def set_muted(self, muted: bool) -> None:
        self._player.audio_set_mute(bool(muted))

    def is_muted(self) -> bool:
        return bool(self._player.audio_get_mute())

    # -- playback rate -----------------------------------------------------

    def set_rate(self, rate: float) -> None:
        """Set playback speed multiplier (1.0 = normal)."""
        self._player.set_rate(float(rate))

    def get_rate(self) -> float:
        return float(self._player.get_rate())

    # -- state -------------------------------------------------------------

    def get_state(self) -> PlaybackState:
        return _VLC_STATE_MAP.get(self._player.get_state(), PlaybackState.IDLE)

    def is_playing(self) -> bool:
        return bool(self._player.is_playing())

    # -- access to raw objects (for video output, events, equalizer) -------

    @property
    def player(self) -> vlc.MediaPlayer:
        return self._player

    @property
    def instance(self) -> vlc.Instance:
        return self._instance

    # -- video output ------------------------------------------------------

    def set_video_window(self, window_id: int) -> None:
        """Embed video output into a native window handle.

        Platform-specific: X11 uses ``set_xwindow``; Windows/macOS would use
        ``set_hwnd``/``set_nsobject``. This app targets Linux.
        """
        try:
            self._player.set_xwindow(int(window_id))
        except Exception:
            pass

    def has_video(self) -> bool:
        """Return True if the current media exposes at least one video track."""
        try:
            return self._player.video_get_track_count() > 0
        except Exception:
            return False

    # -- audio / subtitle tracks ------------------------------------------

    def audio_tracks(self) -> list[tuple[int, str]]:
        """Return [(id, name), ...] for available audio tracks."""
        return _describe(self._player.audio_get_track_description())

    def get_audio_track(self) -> int:
        try:
            return int(self._player.audio_get_track())
        except Exception:
            return -1

    def set_audio_track(self, track_id: int) -> None:
        try:
            self._player.audio_set_track(int(track_id))
        except Exception:
            pass

    def subtitle_tracks(self) -> list[tuple[int, str]]:
        """Return [(id, name), ...] for available subtitle (SPU) tracks."""
        return _describe(self._player.video_get_spu_description())

    def get_subtitle_track(self) -> int:
        try:
            return int(self._player.video_get_spu())
        except Exception:
            return -1

    def set_subtitle_track(self, track_id: int) -> None:
        try:
            self._player.video_set_spu(int(track_id))
        except Exception:
            pass

    # -- external subtitles / snapshot ------------------------------------

    def add_subtitle_file(self, path: str) -> bool:
        """Load an external subtitle file (e.g. .srt). Returns True on success."""
        try:
            uri = _path_to_uri(path)
            rc = self._player.add_slave(vlc.MediaSlaveType.subtitle, uri, True)
            return rc == 0
        except Exception:
            return False

    def take_snapshot(self, path: str, width: int = 0, height: int = 0) -> bool:
        """Save a snapshot of the current video frame to *path*.

        Passing 0 for width/height preserves the source dimensions.
        Returns True on success.
        """
        try:
            rc = self._player.video_take_snapshot(0, path, width, height)
            return rc == 0
        except Exception:
            return False

    def release(self) -> None:
        """Release native resources."""
        try:
            self._player.stop()
            self._player.release()
        except Exception:
            pass


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def _path_to_uri(path: str) -> str:
    """Convert a filesystem path to a file:// URI for libVLC slaves."""
    import pathlib

    return pathlib.Path(path).absolute().as_uri()


def _describe(descriptions) -> list[tuple[int, str]]:
    """Convert a libVLC TrackDescription list into (id, name) tuples."""
    result: list[tuple[int, str]] = []
    if not descriptions:
        return result
    for track_id, name in descriptions:
        if isinstance(name, bytes):
            name = name.decode("utf-8", "replace")
        result.append((int(track_id), str(name)))
    return result
