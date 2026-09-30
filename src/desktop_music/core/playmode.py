"""Shuffle and repeat play-mode logic.

Kept as a small, Qt-agnostic helper so the "what plays next" decision is
unit-testable in isolation from the controller and backend.
"""

from __future__ import annotations

import enum
import random
from typing import Optional


class RepeatMode(enum.Enum):
    """How playback proceeds when a track ends."""

    NONE = "none"      # stop at end of playlist
    ALL = "all"        # wrap around to the first track
    ONE = "one"        # repeat the current track


class PlayMode:
    """Holds shuffle/repeat state and computes the next/previous row."""

    def __init__(self) -> None:
        self.shuffle: bool = False
        self.repeat: RepeatMode = RepeatMode.NONE
        self._rng = random.Random()

    # -- toggles -----------------------------------------------------------

    def toggle_shuffle(self) -> bool:
        self.shuffle = not self.shuffle
        return self.shuffle

    def cycle_repeat(self) -> RepeatMode:
        order = [RepeatMode.NONE, RepeatMode.ALL, RepeatMode.ONE]
        idx = order.index(self.repeat)
        self.repeat = order[(idx + 1) % len(order)]
        return self.repeat

    # -- decisions ---------------------------------------------------------

    def next_row(
        self,
        current: int,
        count: int,
        *,
        auto: bool = False,
    ) -> int:
        """Return the row to play next, or -1 if playback should stop.

        *auto* is True when triggered by a track naturally ending (so
        RepeatMode.ONE re-plays the current track); it is False for an
        explicit user "next" press (which always advances).
        """
        if count <= 0:
            return -1
        if count == 1:
            # Only replay automatically on repeat-one; otherwise stop/stay.
            if auto and self.repeat == RepeatMode.ONE:
                return 0
            if auto and self.repeat == RepeatMode.ALL:
                return 0
            if not auto:
                return 0
            return -1

        if auto and self.repeat == RepeatMode.ONE:
            return current

        if self.shuffle:
            return self._random_other(current, count)

        nxt = current + 1
        if nxt >= count:
            if self.repeat == RepeatMode.ALL:
                return 0
            if not auto:
                return 0  # explicit next wraps for convenience
            return -1  # natural end with no repeat -> stop
        return nxt

    def previous_row(self, current: int, count: int) -> int:
        """Return the previous row (explicit user action)."""
        if count <= 0:
            return -1
        if count == 1:
            return 0
        if self.shuffle:
            return self._random_other(current, count)
        prev = current - 1
        if prev < 0:
            return count - 1  # wrap
        return prev

    def _random_other(self, current: int, count: int) -> int:
        """Pick a random row different from *current* when possible."""
        if count <= 1:
            return 0
        choice = self._rng.randrange(count)
        if choice == current:
            choice = (choice + 1) % count
        return choice

    def seed(self, value: Optional[int]) -> None:
        """Seed the RNG (used by tests for determinism)."""
        self._rng.seed(value)

    # -- persistence -------------------------------------------------------

    def to_state(self) -> dict:
        return {"shuffle": self.shuffle, "repeat": self.repeat.value}

    def load_state(self, state: dict) -> None:
        if not isinstance(state, dict):
            return
        self.shuffle = bool(state.get("shuffle", False))
        try:
            self.repeat = RepeatMode(state.get("repeat", RepeatMode.NONE.value))
        except ValueError:
            self.repeat = RepeatMode.NONE
