"""Shared constants for the application."""

from __future__ import annotations

APP_NAME = "Desktop Music"
ORG_NAME = "desktop-music"

# Supported media extensions (lowercase, with leading dot).
AUDIO_EXTENSIONS: frozenset[str] = frozenset({".mp3", ".flac", ".wav"})
VIDEO_EXTENSIONS: frozenset[str] = frozenset({".mp4", ".mkv", ".avi"})
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
    import os

    return os.path.splitext(path)[1].lower()
