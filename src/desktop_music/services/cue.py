"""CUE sheet parsing.

A ``.cue`` sheet describes the layout of audio data: one or more ``FILE``
entries, each split into ``TRACK`` sections with ``INDEX`` timestamps. A
single large audio file (e.g. a full-album ``.ape``/``.flac``) is commonly
divided into many tracks this way.

For playlist purposes we expand a cue sheet into one entry *per track*:
each :class:`CueTrack` points at the backing media file plus the track's
start offset (and the next track's start as its end offset), so each track
can be played as an individual song. The ``.cue`` file itself is never
added as a playlist item.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from desktop_music.constants import is_media

CUE_EXTENSION = ".cue"

_FILE_LINE = re.compile(
    r'^\s*FILE\s+(?:"([^"]+)"|(\S+))\s+\S+\s*$', re.IGNORECASE
)
_TRACK_LINE = re.compile(r"^\s*TRACK\s+(\d+)\s+\S+\s*$", re.IGNORECASE)
# INDEX 01 MM:SS:FF  (FF = frames, 75 per second)
_INDEX_LINE = re.compile(
    r"^\s*INDEX\s+(\d+)\s+(\d+):(\d+):(\d+)\s*$", re.IGNORECASE
)
_TITLE_LINE = re.compile(r'^\s*TITLE\s+(?:"([^"]*)"|(.+?))\s*$', re.IGNORECASE)
_PERFORMER_LINE = re.compile(
    r'^\s*PERFORMER\s+(?:"([^"]*)"|(.+?))\s*$', re.IGNORECASE
)


@dataclass
class CueTrack:
    """One track carved out of a backing media file by a cue sheet."""

    path: str
    title: str = ""
    artist: str = ""
    start_ms: int = 0
    # End offset in the backing file; 0 means "until end of file".
    end_ms: int = 0


def is_cue(path: str) -> bool:
    """Return True if *path* looks like a cue sheet."""
    return os.path.splitext(path)[1].lower() == CUE_EXTENSION


def _mmssff_to_ms(mm: int, ss: int, ff: int) -> int:
    """Convert a cue ``MM:SS:FF`` timestamp (75 frames/sec) to milliseconds."""
    return (mm * 60 + ss) * 1000 + round(ff * 1000 / 75)


def _unquote(match: re.Match) -> str:
    return (match.group(1) if match.group(1) is not None else match.group(2) or "").strip()


def parse_cue_tracks(cue_path: str) -> list[CueTrack]:
    """Parse *cue_path* into a list of :class:`CueTrack` (one per TRACK).

    Returns an empty list if the sheet can't be read or references no usable
    media file. Each track's ``end_ms`` is set to the next track's start
    within the same backing file (0 for the last track of a file).
    """
    try:
        with open(cue_path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []

    base_dir = os.path.dirname(os.path.abspath(cue_path))

    album_title = ""
    album_artist = ""
    current_file: str | None = None
    tracks: list[CueTrack] = []
    pending: CueTrack | None = None
    seen_track = False  # have we passed the first TRACK yet?

    def flush() -> None:
        nonlocal pending
        if pending is not None:
            tracks.append(pending)
            pending = None

    for line in lines:
        m = _FILE_LINE.match(line)
        if m:
            flush()
            name = m.group(1) or m.group(2)
            current_file = _resolve_reference(base_dir, name) if name else None
            continue

        m = _TRACK_LINE.match(line)
        if m:
            flush()
            seen_track = True
            if current_file is not None:
                pending = CueTrack(
                    path=current_file,
                    artist=album_artist,
                )
            continue

        m = _INDEX_LINE.match(line)
        if m and pending is not None:
            idx = int(m.group(1))
            # INDEX 01 is the track's audible start; prefer it over INDEX 00
            # (pre-gap). Use INDEX 00 only if 01 never appears.
            start = _mmssff_to_ms(int(m.group(2)), int(m.group(3)), int(m.group(4)))
            if idx == 1 or pending.start_ms == 0:
                pending.start_ms = start
            continue

        m = _TITLE_LINE.match(line)
        if m:
            value = _unquote(m)
            if not seen_track:
                album_title = value
            elif pending is not None:
                pending.title = value
            continue

        m = _PERFORMER_LINE.match(line)
        if m:
            value = _unquote(m)
            if not seen_track:
                album_artist = value
                # back-fill tracks created before performer was seen
            elif pending is not None:
                pending.artist = value
            continue

    flush()

    if not tracks:
        return []

    # Fill end_ms from the next track's start within the same file.
    for i, track in enumerate(tracks):
        nxt = tracks[i + 1] if i + 1 < len(tracks) else None
        if nxt is not None and nxt.path == track.path:
            track.end_ms = nxt.start_ms
        else:
            track.end_ms = 0  # last track in this file -> play to the end
        # Default a missing title to the album title / file name.
        if not track.title:
            track.title = album_title or os.path.splitext(
                os.path.basename(track.path)
            )[0]
        if not track.artist:
            track.artist = album_artist
    return tracks


def parse_cue_files(cue_path: str) -> list[str]:
    """Return the distinct backing media files referenced by *cue_path*.

    Kept for callers that only need the file list (order preserved,
    de-duplicated).
    """
    seen: set[str] = set()
    out: list[str] = []
    for t in parse_cue_tracks(cue_path):
        if t.path not in seen:
            seen.add(t.path)
            out.append(t.path)
    return out


def _resolve_reference(base_dir: str, name: str) -> str | None:
    """Resolve a cue ``FILE`` reference to an existing media file, or None.

    First tries the referenced path as-is (absolute, or relative to the cue
    sheet). If that exact path isn't a usable media file, falls back to
    looking for a media file in the same directory sharing the reference's
    base name — this tolerates cue sheets whose ``FILE`` extension doesn't
    match the actual audio file (a common real-world inconsistency).
    """
    candidate = os.path.normpath(
        name if os.path.isabs(name) else os.path.join(base_dir, name)
    )
    if is_media(candidate) and os.path.isfile(candidate):
        return candidate

    ref_dir = os.path.dirname(candidate) or base_dir
    stem = os.path.splitext(os.path.basename(candidate))[0].lower()
    try:
        entries = sorted(os.listdir(ref_dir))
    except OSError:
        return None
    for entry in entries:
        full = os.path.join(ref_dir, entry)
        if not os.path.isfile(full) or not is_media(full):
            continue
        if os.path.splitext(entry)[0].lower() == stem:
            return os.path.normpath(full)
    return None
