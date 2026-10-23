"""MP3 transcoding + a small on-disk LRU cache for browser streaming.

The web remote streams audio to a browser ``<audio>`` element. Browsers can
reliably play MP3, but not every source format the desktop player accepts
(FLAC, APE, WavPack, …). To keep the browser side trivial, every track is
transcoded to a complete MP3 file on demand via ``ffmpeg`` and then served
with HTTP Range support (so the browser can seek and show a real duration).

This module is deliberately Qt-agnostic so it can be unit tested in isolation
and reused from any thread:

* :func:`transcode_to_mp3` produces (or reuses) a cached MP3 for a track,
  optionally limited to a cue-sheet segment via ``start_ms``/``end_ms``.
* :class:`TranscodeCache` owns the cache directory and enforces an LRU bound
  on the number of stored files.

The ffmpeg invocation mirrors the pattern already used by
:mod:`desktop_music.services.spectrum` (quiet, no console window on Windows).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Maximum number of transcoded MP3 files kept on disk at once. When a new
# transcode would exceed this, the least-recently-used file(s) are deleted.
DEFAULT_MAX_CACHE_ENTRIES = 5

# Subdirectory (under the user cache dir) holding transcoded MP3s.
_CACHE_SUBDIR = os.path.join("desktop-music", "stream")


class TranscodeError(RuntimeError):
    """Raised when ffmpeg is unavailable or transcoding fails."""


@dataclass(frozen=True)
class TrackRef:
    """Identifies the exact audio to transcode.

    ``start_ms``/``end_ms`` describe a cue-sheet segment within ``path``;
    both 0 means "the whole file" (``end_ms == 0`` means "to end of file").
    """

    path: str
    start_ms: int = 0
    end_ms: int = 0

    def cache_key(self) -> str:
        """Stable hash of (path, mtime, size, segment) for cache naming.

        Including the file's mtime and size means an edited/replaced source
        file produces a fresh cache entry instead of serving stale audio.
        """
        try:
            st = os.stat(self.path)
            sig = f"{self.path}|{int(st.st_mtime)}|{st.st_size}|{self.start_ms}|{self.end_ms}"
        except OSError:
            sig = f"{self.path}|?|?|{self.start_ms}|{self.end_ms}"
        digest = hashlib.sha1(sig.encode("utf-8")).hexdigest()
        return digest


def default_cache_dir() -> Path:
    """Return the default transcode cache directory (created on demand).

    Honours ``XDG_CACHE_HOME`` when set, else falls back to ``~/.cache``.
    """
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache"
    )
    return Path(base) / _CACHE_SUBDIR


class TranscodeCache:
    """A bounded, on-disk LRU cache of transcoded MP3 files.

    Thread-safe: ``get_or_create`` serializes work so two concurrent requests
    for the same (or different) track don't race on eviction. "Recency" is
    tracked by the file's access/modification time, which we touch on every
    hit, so the cache survives process restarts.
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        *,
        max_entries: int = DEFAULT_MAX_CACHE_ENTRIES,
        ffmpeg: str = "ffmpeg",
    ) -> None:
        self._dir = Path(cache_dir) if cache_dir is not None else default_cache_dir()
        self._max_entries = max(1, int(max_entries))
        self._ffmpeg = ffmpeg
        self._lock = threading.Lock()

    @property
    def cache_dir(self) -> Path:
        return self._dir

    @property
    def max_entries(self) -> int:
        return self._max_entries

    def _path_for(self, ref: TrackRef) -> Path:
        return self._dir / f"{ref.cache_key()}.mp3"

    def get_or_create(self, ref: TrackRef) -> Path:
        """Return a cached MP3 for *ref*, transcoding it if necessary.

        Raises :class:`TranscodeError` on ffmpeg failure. On a cache hit the
        file's timestamp is refreshed so it counts as most-recently-used.
        """
        if not ref.path or not os.path.isfile(ref.path):
            raise TranscodeError(f"source not found: {ref.path!r}")

        with self._lock:
            self._dir.mkdir(parents=True, exist_ok=True)
            out = self._path_for(ref)
            if out.exists() and out.stat().st_size > 0:
                self._touch(out)
                return out

            tmp = out.with_suffix(".mp3.part")
            self._run_ffmpeg(ref, tmp)
            # Atomic-ish publish so a partial file is never served.
            os.replace(tmp, out)
            self._touch(out)
            self._evict_if_needed()
            return out

    def _run_ffmpeg(self, ref: TrackRef, out: Path) -> None:
        cmd: list[str] = [self._ffmpeg, "-v", "quiet", "-y"]
        # Seek before input for speed when a cue segment start is set.
        if ref.start_ms > 0:
            cmd += ["-ss", _ms_to_ffmpeg_time(ref.start_ms)]
        cmd += ["-i", ref.path]
        if ref.end_ms > ref.start_ms:
            # Duration of the segment (relative, since -ss already consumed
            # the lead-in when placed after -i would differ; here -ss is
            # before -i so use -t for the segment length).
            cmd += ["-t", _ms_to_ffmpeg_time(ref.end_ms - ref.start_ms)]
        cmd += [
            "-vn",                 # audio only (drop any cover-art video stream)
            "-map", "0:a:0",       # first audio stream
            "-c:a", "libmp3lame",
            "-q:a", "2",           # VBR ~190 kbps, good quality/size balance
            "-f", "mp3",
            str(out),
        ]
        flags: dict = dict(capture_output=True)
        if sys.platform == "win32":
            flags["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        try:
            result = subprocess.run(cmd, **flags)
        except (FileNotFoundError, OSError) as exc:
            self._cleanup(out)
            raise TranscodeError(f"ffmpeg not available: {exc}") from exc
        if result.returncode != 0 or not out.exists() or out.stat().st_size == 0:
            self._cleanup(out)
            stderr = (result.stderr or b"").decode("utf-8", "replace").strip()
            raise TranscodeError(
                f"ffmpeg failed (code {result.returncode}): {stderr[:200]}"
            )

    def _evict_if_needed(self) -> None:
        """Delete least-recently-used ``*.mp3`` files beyond the bound."""
        files = [p for p in self._dir.glob("*.mp3") if p.is_file()]
        if len(files) <= self._max_entries:
            return
        # Oldest access/modification time first.
        files.sort(key=lambda p: p.stat().st_mtime)
        for victim in files[: len(files) - self._max_entries]:
            self._cleanup(victim)

    @staticmethod
    def _touch(path: Path) -> None:
        try:
            os.utime(path, None)
        except OSError:
            pass

    @staticmethod
    def _cleanup(path: Path) -> None:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass


def _ms_to_ffmpeg_time(ms: int) -> str:
    """Format milliseconds as an ffmpeg time spec ``S.mmm`` (seconds)."""
    ms = max(0, int(ms))
    return f"{ms / 1000.0:.3f}"


# A process-wide default cache, created lazily so importing this module never
# touches the filesystem. Callers that want a custom location/bound can build
# their own :class:`TranscodeCache` instead.
_default_cache: Optional[TranscodeCache] = None
_default_lock = threading.Lock()


def get_default_cache() -> TranscodeCache:
    global _default_cache
    with _default_lock:
        if _default_cache is None:
            _default_cache = TranscodeCache()
        return _default_cache


def transcode_to_mp3(
    path: str,
    start_ms: int = 0,
    end_ms: int = 0,
    *,
    cache: Optional[TranscodeCache] = None,
) -> Path:
    """Transcode *path* (optionally a cue segment) to a cached MP3 file.

    Returns the path to the ready-to-serve MP3. Raises :class:`TranscodeError`
    when ffmpeg is missing or the source cannot be decoded.
    """
    cache = cache or get_default_cache()
    ref = TrackRef(path=path, start_ms=int(start_ms or 0), end_ms=int(end_ms or 0))
    return cache.get_or_create(ref)
