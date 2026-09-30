"""JSON persistence for settings and the playlist.

State is stored under the user's config directory
(``~/.config/desktop-music/state.json`` on Linux). The schema is a single
flat dict; unknown keys are preserved on load so future versions can add
fields without breaking older state files.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any


def default_config_dir() -> str:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Local"
        )
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
            os.path.expanduser("~"), ".config"
        )
    return os.path.join(base, "desktop-music")


class SettingsStore:
    """Load/save a flat dict of application state to a JSON file."""

    def __init__(self, path: str | None = None) -> None:
        self._path = path or os.path.join(default_config_dir(), "state.json")
        self._data: dict[str, Any] = {}

    @property
    def path(self) -> str:
        return self._path

    @property
    def data(self) -> dict[str, Any]:
        return self._data

    # -- access ------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def update(self, values: dict[str, Any]) -> None:
        self._data.update(values)

    # -- io ----------------------------------------------------------------

    def load(self) -> dict[str, Any]:
        """Load state from disk (returns empty dict if missing/corrupt)."""
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                self._data = loaded
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self._data = {}
        return self._data

    def save(self) -> None:
        """Persist state to disk atomically."""
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self._path)
