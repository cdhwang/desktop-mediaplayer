"""Lyrics extraction.

Resolution order for a given media file:
  1. embedded lyrics tags (ID3 ``USLT``, or Vorbis ``LYRICS``/``UNSYNCEDLYRICS``)
  2. a sidecar text file with the same stem (``.lrc`` preferred, then ``.txt``)

Per Task 5=b the display is plain text; ``.lrc`` timestamp tags (``[mm:ss]``)
are stripped so the raw lyric lines are shown. Everything is best-effort:
failures yield an empty string.
"""

from __future__ import annotations

import os
import re

import mutagen
from mutagen.flac import FLAC

_LRC_TIMESTAMP = re.compile(r"\[\d{1,2}:\d{2}(?:[.:]\d{1,3})?\]")
_SIDECAR_EXTS = (".lrc", ".txt")


def read_lyrics(path: str) -> str:
    """Return lyrics for *path* (embedded first, then sidecar), or ""."""
    embedded = _read_embedded(path)
    if embedded:
        return embedded.strip()

    sidecar = _read_sidecar(path)
    if sidecar:
        return _strip_lrc_timestamps(sidecar).strip()

    return ""


def _read_embedded(path: str) -> str:
    try:
        audio = mutagen.File(path)
    except Exception:
        return ""
    if audio is None:
        return ""

    # FLAC / Vorbis comments
    if isinstance(audio, FLAC) or (
        hasattr(audio, "get") and not hasattr(getattr(audio, "tags", None), "getall")
    ):
        for key in ("lyrics", "LYRICS", "unsyncedlyrics", "UNSYNCEDLYRICS"):
            try:
                value = audio.get(key)
            except Exception:
                value = None
            if value:
                return value[0] if isinstance(value, (list, tuple)) else str(value)

    # ID3 USLT frames
    tags = getattr(audio, "tags", None)
    if tags is not None and hasattr(tags, "getall"):
        try:
            frames = tags.getall("USLT")
        except Exception:
            frames = []
        if frames:
            return str(frames[0].text)

    return ""


def _read_sidecar(path: str) -> str:
    stem, _ = os.path.splitext(path)
    for ext in _SIDECAR_EXTS:
        candidate = stem + ext
        if os.path.exists(candidate):
            try:
                with open(candidate, "r", encoding="utf-8", errors="replace") as fh:
                    return fh.read()
            except OSError:
                continue
    return ""


def _strip_lrc_timestamps(text: str) -> str:
    lines = []
    for line in text.splitlines():
        cleaned = _LRC_TIMESTAMP.sub("", line).strip()
        # drop pure LRC metadata lines like [ar:...] [ti:...]
        if re.fullmatch(r"\[[a-zA-Z]+:.*\]", cleaned):
            continue
        lines.append(cleaned)
    return "\n".join(lines)
