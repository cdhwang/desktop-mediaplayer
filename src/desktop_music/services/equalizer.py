"""Audio equalizer using libVLC's built-in presets.

Presets (Flat, Rock, Pop, Classical, ...) are enumerated from libVLC and
applied to the media player via ``set_equalizer``. The chosen preset index
is persisted by the main window through :class:`SettingsStore`.
"""

from __future__ import annotations

import vlc

# index used to represent "no equalizer" (bypass).
PRESET_NONE = -1


def preset_names() -> list[str]:
    """Return the list of built-in preset names (index == list position)."""
    count = vlc.libvlc_audio_equalizer_get_preset_count()
    names: list[str] = []
    for i in range(count):
        raw = vlc.libvlc_audio_equalizer_get_preset_name(i)
        names.append(raw.decode("utf-8", "replace") if raw else f"Preset {i}")
    return names


class EqualizerService:
    """Applies EQ presets to a :class:`VLCBackend`'s media player."""

    def __init__(self, backend) -> None:
        self._backend = backend
        self._preset_index: int = PRESET_NONE
        self._presets = preset_names()

    @property
    def presets(self) -> list[str]:
        return list(self._presets)

    @property
    def preset_index(self) -> int:
        return self._preset_index

    def apply_preset(self, index: int) -> bool:
        """Apply preset *index*; ``PRESET_NONE`` disables the equalizer.

        Returns True on success.
        """
        player = self._backend.player
        if index == PRESET_NONE:
            # Passing None removes any active equalizer.
            ok = player.set_equalizer(None) == 0
            if ok:
                self._preset_index = PRESET_NONE
            return ok

        if not (0 <= index < len(self._presets)):
            return False

        eq = vlc.libvlc_audio_equalizer_new_from_preset(index)
        if eq is None:
            return False
        ok = player.set_equalizer(eq) == 0
        if ok:
            self._preset_index = index
        return ok
