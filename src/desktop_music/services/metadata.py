"""Metadata extraction using mutagen.

Reads title/artist/album/duration and embedded cover art from audio files.
Everything is best-effort: unreadable or tag-less files yield an empty
:class:`Metadata` rather than raising, so the UI can always fall back to
the file name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import mutagen
from mutagen.flac import FLAC
from mutagen.id3 import ID3


@dataclass
class Metadata:
    """Extracted tags for a single media file."""

    title: str = ""
    artist: str = ""
    album: str = ""
    duration_ms: int = 0
    cover_art: Optional[bytes] = None
    codec: str = ""           # e.g. "MP3", "FLAC"
    bitrate_kbps: int = 0     # e.g. 320
    sample_rate: int = 0      # e.g. 44100

    @property
    def tech_info(self) -> str:
        """PotPlayer-style one-line technical summary, e.g. 'MP3 320kbps 44.1khz'."""
        parts: list[str] = []
        if self.codec:
            parts.append(self.codec)
        if self.bitrate_kbps:
            parts.append(f"{self.bitrate_kbps}kbps")
        if self.sample_rate:
            parts.append(f"{self.sample_rate / 1000:.1f}khz")
        return " ".join(parts)


def read_metadata(path: str) -> Metadata:
    """Read tags from *path*; returns an empty Metadata on any failure."""
    try:
        audio = mutagen.File(path)
    except Exception:
        audio = None
    if audio is None:
        return Metadata()

    meta = Metadata()

    # Duration is available on the shared .info object.
    info = getattr(audio, "info", None)
    if info is not None and getattr(info, "length", None):
        meta.duration_ms = int(info.length * 1000)
    if info is not None:
        bitrate = getattr(info, "bitrate", 0) or 0
        meta.bitrate_kbps = int(bitrate / 1000) if bitrate else 0
        meta.sample_rate = int(getattr(info, "sample_rate", 0) or 0)
    meta.codec = _codec_name(path, audio)

    # Common (EasyID3-like / Vorbis) tag access via .tags mapping.
    meta.title = _first_tag(audio, ("title", "TIT2"))
    meta.artist = _first_tag(audio, ("artist", "TPE1"))
    meta.album = _first_tag(audio, ("album", "TALB"))

    meta.cover_art = _extract_cover(path, audio)
    return meta


def _codec_name(path: str, audio) -> str:
    """Best-effort codec label from the file extension."""
    import os

    ext = os.path.splitext(path)[1].lower().lstrip(".")
    mapping = {
        "mp3": "MP3",
        "flac": "FLAC",
        "wav": "WAV",
        "m4a": "AAC",
        "ogg": "OGG",
        "opus": "OPUS",
        "mp4": "MP4",
        "mkv": "MKV",
        "avi": "AVI",
    }
    return mapping.get(ext, ext.upper())


def _first_tag(audio, keys: tuple[str, ...]) -> str:
    tags = getattr(audio, "tags", None)
    if not tags:
        return ""
    for key in keys:
        try:
            value = tags.get(key)
        except Exception:
            value = None
        if value is None:
            continue
        # ID3 frames expose .text; vorbis comments are lists of str.
        text = getattr(value, "text", value)
        if isinstance(text, (list, tuple)):
            if text:
                return str(text[0])
        elif text:
            return str(text)
    return ""


def _extract_cover(path: str, audio) -> Optional[bytes]:
    """Return embedded cover art bytes if present."""
    # FLAC stores pictures directly.
    if isinstance(audio, FLAC):
        if audio.pictures:
            return bytes(audio.pictures[0].data)
        return None

    # MP3 / ID3: look for an APIC frame.
    tags = getattr(audio, "tags", None)
    if isinstance(tags, ID3) or (tags is not None and hasattr(tags, "getall")):
        try:
            apics = tags.getall("APIC")
        except Exception:
            apics = []
        if apics:
            return bytes(apics[0].data)

    return None
