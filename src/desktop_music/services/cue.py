"""CUE sheet parsing.

A ``.cue`` sheet describes the layout of one or more audio files (and the
tracks within them). For playlist purposes we only care about the audio
files it references via ``FILE "..." <TYPE>`` lines — we expand a cue sheet
into the media files it points at, and never add the ``.cue`` file itself.

The referenced paths are resolved relative to the directory containing the
cue sheet, filtered to supported, existing media files, and de-duplicated
while preserving order.
"""

from __future__ import annotations

import os
import re

from desktop_music.constants import is_media

CUE_EXTENSION = ".cue"

# Matches:  FILE "Some Album.flac" WAVE   /   FILE Track.wav WAVE
# The filename may be quoted (allowing spaces) or a single bare token.
_FILE_LINE = re.compile(
    r'^\s*FILE\s+(?:"([^"]+)"|(\S+))\s+\S+\s*$',
    re.IGNORECASE,
)


def is_cue(path: str) -> bool:
    """Return True if *path* looks like a cue sheet."""
    return os.path.splitext(path)[1].lower() == CUE_EXTENSION


def parse_cue_files(cue_path: str) -> list[str]:
    """Return the media files referenced by the cue sheet at *cue_path*.

    Paths are resolved relative to the cue sheet's directory, restricted to
    supported, existing media files, and de-duplicated (order preserved).
    Returns an empty list if the cue sheet can't be read or references
    nothing usable.
    """
    try:
        # Cue sheets are commonly latin-1/utf-8; be lenient about encoding.
        with open(cue_path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return []

    base_dir = os.path.dirname(os.path.abspath(cue_path))
    seen: set[str] = set()
    result: list[str] = []
    for line in text.splitlines():
        match = _FILE_LINE.match(line)
        if not match:
            continue
        name = match.group(1) or match.group(2)
        if not name:
            continue
        candidate = os.path.normpath(
            name if os.path.isabs(name) else os.path.join(base_dir, name)
        )
        if not is_media(candidate):
            continue
        if not os.path.isfile(candidate):
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        result.append(candidate)
    return result
