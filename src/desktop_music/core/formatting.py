"""Small formatting helpers."""

from __future__ import annotations


def format_ms(ms: int) -> str:
    """Format milliseconds as ``m:ss`` or ``h:mm:ss``."""
    if ms < 0:
        ms = 0
    total_seconds = ms // 1000
    hours, rem = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"
