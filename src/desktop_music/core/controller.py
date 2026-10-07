"""PlayerController: bridges the VLC backend to the Qt UI via signals.

Responsibilities:
  * expose high-level transport operations (play/pause, seek, volume)
  * poll the backend on a timer and emit position/state changes
  * translate command ids into backend calls

Playlist navigation (next/previous), shuffle/repeat, video and rate
controls are layered on in later tasks; this controller already exposes
signals and stubs for them so the control bar can wire up now.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from desktop_music.core.playmode import PlayMode, RepeatMode
from desktop_music.services.backend import PlaybackState, VLCBackend

# How far a single seek command jumps, in milliseconds.
SEEK_STEP_MS = 5_000
# How far a "long" seek command jumps (Shift+arrow), in milliseconds.
SEEK_STEP_LONG_MS = 60_000
# Volume increment for volume up/down commands.
VOLUME_STEP = 5
# Playback rate step and bounds.
RATE_STEP = 0.1
RATE_MIN = 0.25
RATE_MAX = 4.0
# Position polling interval.
_POLL_INTERVAL_MS = 250


class PlayerController(QObject):
    """UI-facing controller around :class:`VLCBackend`."""

    # emitted every poll while media is loaded: (position_ms, length_ms)
    position_changed = pyqtSignal(int, int)
    # emitted when normalized playback state changes
    state_changed = pyqtSignal(PlaybackState)
    # emitted when volume changes: (volume 0..100, muted)
    volume_changed = pyqtSignal(int, bool)
    # emitted when the current media source changes (path or None)
    media_changed = pyqtSignal(object)
    # emitted when playback reaches the end of the current media
    playback_ended = pyqtSignal()
    # emitted when shuffle or repeat mode changes
    play_mode_changed = pyqtSignal()
    # emitted when playback rate changes (new rate multiplier)
    rate_changed = pyqtSignal(float)

    def __init__(self, backend: VLCBackend | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._backend = backend or VLCBackend()
        self._last_state: PlaybackState = PlaybackState.IDLE
        self._playlist = None  # type: ignore[assignment]
        self._play_mode = PlayMode()

        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

        # auto-advance to the next track when playback ends
        self.playback_ended.connect(self._on_playback_ended)

    @property
    def backend(self) -> VLCBackend:
        return self._backend

    # -- playlist integration ---------------------------------------------

    def set_playlist(self, model) -> None:
        """Attach a :class:`PlaylistModel` for next/previous navigation."""
        self._playlist = model

    @property
    def playlist(self):
        return self._playlist

    def play_row(self, row: int, autoplay: bool = True) -> None:
        """Make *row* current in the playlist and play its track."""
        if self._playlist is None:
            return
        self._playlist.set_current(row)
        track = self._playlist.track_at(row)
        if track is not None:
            self.open(track.path, autoplay=autoplay)

    def next(self) -> None:
        """Advance to the next track (explicit user action)."""
        if self._playlist is None:
            return
        row = self._play_mode.next_row(
            self._playlist.current_index, self._playlist.rowCount(), auto=False
        )
        if row >= 0:
            self.play_row(row)

    def previous(self) -> None:
        """Go to the previous track (explicit user action)."""
        if self._playlist is None:
            return
        row = self._play_mode.previous_row(
            self._playlist.current_index, self._playlist.rowCount()
        )
        if row >= 0:
            self.play_row(row)

    # -- play mode (shuffle / repeat) -------------------------------------

    @property
    def play_mode(self) -> PlayMode:
        return self._play_mode

    def toggle_shuffle(self) -> bool:
        state = self._play_mode.toggle_shuffle()
        self.play_mode_changed.emit()
        return state

    def cycle_repeat(self) -> RepeatMode:
        mode = self._play_mode.cycle_repeat()
        self.play_mode_changed.emit()
        return mode

    def _on_playback_ended(self) -> None:
        """Auto-advance when a track ends naturally."""
        if self._playlist is None or self._playlist.rowCount() == 0:
            return
        row = self._play_mode.next_row(
            self._playlist.current_index, self._playlist.rowCount(), auto=True
        )
        if row >= 0:
            self.play_row(row)

    # -- media -------------------------------------------------------------

    def open(self, path: str, autoplay: bool = True) -> None:
        """Load *path* and optionally begin playback."""
        self._backend.load(path)
        self.media_changed.emit(path)
        if autoplay:
            self.play()

    # -- transport ---------------------------------------------------------

    def play(self) -> None:
        self._backend.play()

    def toggle_pause(self) -> None:
        self._backend.toggle_pause()

    def stop(self) -> None:
        self._backend.stop()

    def seek_to_ms(self, ms: int) -> None:
        self._backend.seek(ms)

    def seek_to_fraction(self, fraction: float) -> None:
        self._backend.set_position(fraction)

    def seek_relative(self, delta_ms: int) -> None:
        current = self._backend.get_time()
        if current < 0:
            current = 0
        self._backend.seek(current + delta_ms)

    # -- volume ------------------------------------------------------------

    def set_volume(self, volume: int) -> None:
        self._backend.set_volume(volume)
        self.volume_changed.emit(self._backend.get_volume(), self._backend.is_muted())

    def change_volume(self, delta: int) -> None:
        self.set_volume(self._backend.get_volume() + delta)

    def toggle_mute(self) -> None:
        self._backend.set_muted(not self._backend.is_muted())
        self.volume_changed.emit(self._backend.get_volume(), self._backend.is_muted())

    # -- playback rate -----------------------------------------------------

    def set_rate(self, rate: float) -> None:
        self._backend.set_rate(_clamp_rate(rate))
        self.rate_changed.emit(self._backend.get_rate())

    def change_rate(self, delta: float) -> None:
        self.set_rate(self._backend.get_rate() + delta)

    def reset_rate(self) -> None:
        self.set_rate(1.0)

    # -- command dispatch --------------------------------------------------

    def dispatch(self, command_id: str) -> None:
        """Execute a named command (see :mod:`desktop_music.core.commands`)."""
        from desktop_music.core import commands as cmd

        handlers = {
            cmd.PLAY_PAUSE: self.toggle_pause,
            cmd.STOP: self.stop,
            cmd.NEXT: self.next,
            cmd.PREVIOUS: self.previous,
            cmd.SEEK_FORWARD: lambda: self.seek_relative(SEEK_STEP_MS),
            cmd.SEEK_BACKWARD: lambda: self.seek_relative(-SEEK_STEP_MS),
            cmd.SEEK_FORWARD_LONG: lambda: self.seek_relative(SEEK_STEP_LONG_MS),
            cmd.SEEK_BACKWARD_LONG: lambda: self.seek_relative(-SEEK_STEP_LONG_MS),
            cmd.VOLUME_UP: lambda: self.change_volume(VOLUME_STEP),
            cmd.VOLUME_DOWN: lambda: self.change_volume(-VOLUME_STEP),
            cmd.MUTE: self.toggle_mute,
            cmd.TOGGLE_SHUFFLE: self.toggle_shuffle,
            cmd.CYCLE_REPEAT: self.cycle_repeat,
            cmd.RATE_UP: lambda: self.change_rate(RATE_STEP),
            cmd.RATE_DOWN: lambda: self.change_rate(-RATE_STEP),
            cmd.RATE_RESET: self.reset_rate,
        }
        handler = handlers.get(command_id)
        if handler is not None:
            handler()

    # -- polling -----------------------------------------------------------

    def _poll(self) -> None:
        state = self._backend.get_state()
        if state != self._last_state:
            self._last_state = state
            self.state_changed.emit(state)
            if state == PlaybackState.ENDED:
                self.playback_ended.emit()

        length = self._backend.get_length()
        time_ms = self._backend.get_time()
        if time_ms < 0:
            time_ms = 0
        self.position_changed.emit(time_ms, length)

    # -- lifecycle ---------------------------------------------------------

    def shutdown(self) -> None:
        self._timer.stop()
        self._backend.release()


def _clamp_rate(rate: float) -> float:
    return max(RATE_MIN, min(RATE_MAX, float(rate)))
