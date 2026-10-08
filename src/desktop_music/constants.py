"""Shared constants for the application."""

from __future__ import annotations

import os

APP_NAME = "Desktop Music"
ORG_NAME = "desktop-music"

# Directory holding bundled resources (icons, etc.).
RESOURCES_DIR = os.path.join(os.path.dirname(__file__), "resources")
APP_ICON_PATH = os.path.join(RESOURCES_DIR, "app_icon.png")

# Individual rendered sizes, used to build a crisp multi-resolution QIcon.
_APP_ICON_SIZES = (16, 32, 48, 64, 128, 256)


def load_app_icon():
    """Return a multi-resolution QIcon for the application, or an empty one.

    Adds every rendered PNG size so the window manager / taskbar can pick the
    sharpest bitmap for the context. Imported lazily to keep this module free
    of a hard Qt dependency for non-GUI consumers (e.g. unit tests).
    """
    from PyQt6.QtGui import QIcon

    icon = QIcon()
    added = False
    for size in _APP_ICON_SIZES:
        path = os.path.join(RESOURCES_DIR, f"app_icon_{size}.png")
        if os.path.exists(path):
            icon.addFile(path)
            added = True
    if not added and os.path.exists(APP_ICON_PATH):
        icon.addFile(APP_ICON_PATH)
    return icon

# Supported media extensions (lowercase, with leading dot).
# libVLC decodes a wide range of formats; include common lossless/lossy
# audio containers (e.g. Monkey's Audio ``.ape``, often referenced by cue
# sheets) so they are accepted by directory scans, drops, and cue parsing.
AUDIO_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".mp3",
        ".flac",
        ".wav",
        ".ape",
        ".m4a",
        ".aac",
        ".ogg",
        ".opus",
        ".wma",
        ".wv",
        ".tta",
        ".alac",
        ".aiff",
        ".aif",
    }
)
VIDEO_EXTENSIONS: frozenset[str] = frozenset(
    {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg"}
)
MEDIA_EXTENSIONS: frozenset[str] = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS


def is_audio(path: str) -> bool:
    """Return True if *path* has a supported audio extension."""
    return _ext(path) in AUDIO_EXTENSIONS


def is_video(path: str) -> bool:
    """Return True if *path* has a supported video extension."""
    return _ext(path) in VIDEO_EXTENSIONS


def is_media(path: str) -> bool:
    """Return True if *path* has any supported media extension."""
    return _ext(path) in MEDIA_EXTENSIONS


def _ext(path: str) -> str:
    return os.path.splitext(path)[1].lower()
