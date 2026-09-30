"""Shared pytest configuration.

Force Qt to use the offscreen platform when no display is available so
GUI tests can run headlessly (CI, containers).
"""

from __future__ import annotations

import os

if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
