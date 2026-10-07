"""Helpers for drag-and-drop of media files/folders."""

from __future__ import annotations

import os

from desktop_music.constants import MEDIA_EXTENSIONS, is_media
from desktop_music.services.cue import is_cue


def _is_droppable(path: str) -> bool:
    """A local path we accept: a directory, a media file, or a cue sheet."""
    return os.path.isdir(path) or is_media(path) or is_cue(path)


def has_media_urls(mime) -> bool:
    """Return True if a QMimeData carries at least one local file/folder URL."""
    if not mime.hasUrls():
        return False
    for url in mime.urls():
        if url.isLocalFile() and _is_droppable(url.toLocalFile()):
            return True
    return False


def extract_paths(mime) -> list[str]:
    """Extract local media files and directories from dropped QMimeData.

    Directories are returned as-is (the playlist model scans them
    recursively); individual files are filtered to supported media types and
    ``.cue`` sheets (which the model expands into their referenced files).
    """
    paths: list[str] = []
    if not mime.hasUrls():
        return paths
    for url in mime.urls():
        if not url.isLocalFile():
            continue
        path = url.toLocalFile()
        if _is_droppable(path):
            paths.append(path)
    return paths


__all__ = ["has_media_urls", "extract_paths", "MEDIA_EXTENSIONS"]
