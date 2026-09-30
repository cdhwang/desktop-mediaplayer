"""Named command registry.

Every user-triggerable action is defined here as a :class:`Command` with a
stable string id, a human label, and a default key sequence. The control
bar (Task 3), menu bar (Task 15), and customizable shortcut system
(Task 14) all bind against these ids so behaviour stays consistent.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Command:
    """A named, bindable user action."""

    id: str
    label: str
    default_shortcut: str = ""


# -- command ids (use these constants instead of raw strings) --------------

PLAY_PAUSE = "play_pause"
STOP = "stop"
NEXT = "next"
PREVIOUS = "previous"
SEEK_FORWARD = "seek_forward"
SEEK_BACKWARD = "seek_backward"
VOLUME_UP = "volume_up"
VOLUME_DOWN = "volume_down"
MUTE = "mute"
FULLSCREEN = "fullscreen"
SNAPSHOT = "snapshot"
RATE_UP = "rate_up"
RATE_DOWN = "rate_down"
RATE_RESET = "rate_reset"
TOGGLE_SHUFFLE = "toggle_shuffle"
CYCLE_REPEAT = "cycle_repeat"


# -- registry --------------------------------------------------------------

COMMANDS: tuple[Command, ...] = (
    Command(PLAY_PAUSE, "Play / Pause", "Space"),
    Command(STOP, "Stop", "S"),
    Command(NEXT, "Next Track", "Ctrl+Right"),
    Command(PREVIOUS, "Previous Track", "Ctrl+Left"),
    Command(SEEK_FORWARD, "Seek Forward", "Right"),
    Command(SEEK_BACKWARD, "Seek Backward", "Left"),
    Command(VOLUME_UP, "Volume Up", "Up"),
    Command(VOLUME_DOWN, "Volume Down", "Down"),
    Command(MUTE, "Mute / Unmute", "M"),
    Command(FULLSCREEN, "Toggle Fullscreen", "F"),
    Command(SNAPSHOT, "Take Snapshot", "Ctrl+S"),
    Command(RATE_UP, "Speed Up", "]"),
    Command(RATE_DOWN, "Slow Down", "["),
    Command(RATE_RESET, "Reset Speed", "\\"),
    Command(TOGGLE_SHUFFLE, "Toggle Shuffle", "Ctrl+H"),
    Command(CYCLE_REPEAT, "Cycle Repeat Mode", "Ctrl+R"),
)

COMMANDS_BY_ID: dict[str, Command] = {c.id: c for c in COMMANDS}


def default_shortcuts() -> dict[str, str]:
    """Return a mapping of command id -> default key sequence."""
    return {c.id: c.default_shortcut for c in COMMANDS}
