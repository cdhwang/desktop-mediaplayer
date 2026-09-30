"""Helpers for drag-and-drop of media files/folders."""

from __future__ import annotations

import os

from desktop_music.constants import MEDIA_EXTENSIONS, is_media


def has_media_urls(mime) -> bool:
    """Return True if a QMimeData carries at least one local file/folder URL."""
    if not mime.hasUrls():
        return False
    for url in mime.urls():
        if url.isLocalFile():
            path = url.toLocalFile()
            if os.path.isdir(path) or is_media(path):
                return True
    return False


def extract_paths(mime) -> list[str]:
    """Extract local media files and directories from dropped QMimeData.

    Directories are returned as-is (the playlist model scans them
    recursively); individual files are filtered to supported media types.
    """
    paths: list[str] = []
    if not mime.hasUrls():
        return paths
    for url in mime.urls():
        if not url.isLocalFile():
            continue
        path = url.toLocalFile()
        if os.path.isdir(path) or is_media(path):
            paths.append(path)
    return paths


__all__ = ["has_media_urls", "extract_paths", "MEDIA_EXTENSIONS"]
