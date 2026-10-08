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
    # emitted right after an explicit seek: (position_ms, length_ms),
    # both relative to the current cue segment when one is active
    seeked = pyqtSignal(int, int)
    # emitted when the audio normalizer is toggled (new on/off state)
    normalize_changed = pyqtSignal(bool)

    def __init__(self, backend: VLCBackend | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._backend = backend or VLCBackend()
        self._last_state: PlaybackState = PlaybackState.IDLE
        self._playlist = None  # type: ignore[assignment]
        self._play_mode = PlayMode()

        # Last volume we *requested* (0..100). We track this ourselves instead
        # of reading it back from libVLC: while playing, ``audio_get_volume``
        # can briefly return the previous value right after ``audio_set_volume``
        # (volume is applied asynchronously), which would make the OSD and
        # slider show a stale value. Seeded from the backend's current volume
        # when available (guarded so non-GUI/mock backends can't break init).
        try:
            self._volume: int = int(self._backend.get_volume())
        except (TypeError, ValueError):
            self._volume = 100

        # Current cue-track segment within the backing file (ms). When
        # ``_seg_end`` > 0 playback is confined to [_seg_start, _seg_end) and
        # auto-advances at the boundary. ``_seg_start``/``_seg_end`` are 0 for
        # ordinary whole-file tracks.
        self._seg_start = 0
        self._seg_end = 0
        self._seg_pending_seek = False

        # Optional hook invoked after the backend is rebuilt (e.g. when the
        # audio normalizer is toggled), so the UI can re-attach video output
        # to the new MediaPlayer. Set by the window via set_backend_rebuilt_hook.
        self._on_backend_rebuilt = None  # type: ignore[assignment]

        # Deferred resume-seek after a backend rebuild (normalizer toggle).
        self._resume_pending = False
        self._resume_seek_ms = 0
        self._resume_pause = False

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
            self._seg_start = getattr(track, "start_ms", 0) or 0
            self._seg_end = getattr(track, "end_ms", 0) or 0
            # If several cue tracks share one backing file we can seek within
            # the already-loaded media instead of reloading it.
            same_file = self._backend.current_path == track.path
            if same_file and self._seg_start >= 0:
                self._backend.seek(self._seg_start)
                self._seg_pending_seek = False
                self.media_changed.emit(track.path)
                if autoplay:
                    self.play()
            else:
                self._seg_pending_seek = self._seg_start > 0
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
            self.stop()
            return
        row = self._play_mode.next_row(
            self._playlist.current_index, self._playlist.rowCount(), auto=True
        )
        if row >= 0:
            self.play_row(row)
        else:
            # No next track (end of playlist, no repeat). Stop playback
            # explicitly so a cue segment that ends mid-file doesn't let the
            # backing media keep playing past the current track's boundary.
            self.stop()

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
        # Interpret *ms* relative to the current cue segment, if any.
        self._backend.seek(self._seg_start + max(0, ms))
        self._emit_seeked()

    def seek_to_fraction(self, fraction: float) -> None:
        if self._seg_start > 0 or self._seg_end > 0:
            length = self._backend.get_length()
            seg_len = (
                self._seg_end - self._seg_start
                if self._seg_end > self._seg_start
                else max(0, length - self._seg_start)
            )
            self._backend.seek(self._seg_start + int(seg_len * fraction))
        else:
            self._backend.set_position(fraction)
        self._emit_seeked()

    def seek_relative(self, delta_ms: int) -> None:
        current = self._backend.get_time()
        if current < 0:
            current = 0
        target = current + delta_ms
        # Keep seeks within the current cue segment.
        if self._seg_start > 0:
            target = max(self._seg_start, target)
        if self._seg_end > self._seg_start:
            target = min(target, self._seg_end - 1)
        self._backend.seek(target)
        self._emit_seeked()

    def _emit_seeked(self) -> None:
        """Emit :attr:`seeked` with the post-seek position (segment-relative)."""
        length = self._backend.get_length()
        time_ms = self._backend.get_time()
        if time_ms < 0:
            time_ms = 0
        if self._seg_start > 0 or self._seg_end > 0:
            seg_len = (
                self._seg_end - self._seg_start
                if self._seg_end > self._seg_start
                else max(0, length - self._seg_start)
            )
            rel = max(0, time_ms - self._seg_start)
            self.seeked.emit(rel, seg_len)
        else:
            self.seeked.emit(time_ms, length)

    # -- volume ------------------------------------------------------------

    @property
    def volume(self) -> int:
        """The last volume we requested (0..100).

        Prefer this over ``backend.get_volume()`` for display and persistence:
        it reflects the user's intent immediately, without libVLC's playback
        read-back lag.
        """
        return self._volume

    def set_volume(self, volume: int) -> None:
        # Trust the value the backend reports it *applied* (clamped), not a
        # read-back of libVLC's live volume, which lags during playback.
        applied = self._backend.set_volume(volume)
        try:
            self._volume = int(applied)
        except (TypeError, ValueError):
            # Backend didn't return a usable number (e.g. a bare mock);
            # fall back to the requested value, clamped.
            self._volume = max(0, min(100, int(volume)))
        self.volume_changed.emit(self._volume, self._backend.is_muted())

    def change_volume(self, delta: int) -> None:
        # Base the delta on our tracked request value, not a live read-back,
        # so repeated steps during playback don't accumulate from stale values.
        self.set_volume(self._volume + delta)

    def toggle_mute(self) -> None:
        self._backend.set_muted(not self._backend.is_muted())
        self.volume_changed.emit(self._volume, self._backend.is_muted())

    # -- audio normalizer --------------------------------------------------

    @property
    def normalize(self) -> bool:
        """Whether the volume normalizer (normvol) is currently enabled."""
        return getattr(self._backend, "normalize", False) is True

    def set_backend_rebuilt_hook(self, hook) -> None:
        """Register a callable invoked after the backend is rebuilt.

        The UI uses this to re-attach video output to the fresh MediaPlayer,
        since toggling the normalizer replaces the whole backend instance.
        """
        self._on_backend_rebuilt = hook

    def set_normalize(self, enabled: bool) -> None:
        """Enable/disable the audio normalizer.

        libVLC fixes the audio-filter chain at instance creation, so this
        rebuilds the backend with the new setting and restores the current
        playback state (track, position, volume, mute, rate, play/pause).
        """
        enabled = bool(enabled)
        if enabled == self.normalize:
            return

        # --- snapshot current playback state ---
        path = self._backend.current_path
        was_playing = self._backend.is_playing()
        state = self._backend.get_state()
        was_paused = state == PlaybackState.PAUSED
        time_ms = self._backend.get_time()
        if time_ms < 0:
            time_ms = 0
        muted = self._backend.is_muted()
        rate = self._backend.get_rate()
        volume = self._volume

        # --- rebuild backend with the new filter setting ---
        self._backend.release()
        self._backend = VLCBackend(normalize=enabled)

        # Let the UI re-attach video output to the new player before playback.
        if self._on_backend_rebuilt is not None:
            try:
                self._on_backend_rebuilt(self._backend)
            except Exception:
                pass

        # --- restore state ---
        self._volume = self._backend.set_volume(volume)
        self._backend.set_muted(muted)
        self._backend.set_rate(rate)
        if path:
            self._backend.load(path)
            if was_playing or was_paused:
                self._backend.play()
                # Seek back to where we were; defer via the segment-pending
                # mechanism so the seek lands after playback actually starts
                # (seeking before play() often no-ops in libVLC).
                self._resume_seek_ms = max(0, time_ms)
                self._resume_pending = True
                if was_paused:
                    # settle into paused state after the resume seek
                    self._resume_pause = True
                else:
                    self._resume_pause = False
            else:
                self._resume_pending = False
        else:
            self._resume_pending = False

        self.normalize_changed.emit(self.normalize)
        # re-emit volume so the slider/OSD reflect the restored backend
        self.volume_changed.emit(self._volume, self._backend.is_muted())

    def toggle_normalize(self) -> bool:
        """Flip the normalizer on/off and return the new state."""
        self.set_normalize(not self.normalize)
        return self.normalize

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

        # After a backend rebuild (normalizer toggle), restore the playback
        # position once the new player is actually running, then optionally
        # settle back into a paused state.
        if self._resume_pending and state in (
            PlaybackState.PLAYING,
            PlaybackState.BUFFERING,
        ):
            if self._resume_seek_ms > 0:
                self._backend.seek(self._resume_seek_ms)
            if self._resume_pause:
                self._backend.pause()
            self._resume_pending = False

        # Apply a deferred seek to the cue-track start once the media is
        # actually playing (seeking before play() often no-ops in libVLC).
        if self._seg_pending_seek and state in (
            PlaybackState.PLAYING,
            PlaybackState.BUFFERING,
        ):
            self._backend.seek(self._seg_start)
            self._seg_pending_seek = False

        if state != self._last_state:
            self._last_state = state
            self.state_changed.emit(state)
            if state == PlaybackState.ENDED:
                self.playback_ended.emit()

        length = self._backend.get_length()
        time_ms = self._backend.get_time()
        if time_ms < 0:
            time_ms = 0

        # Cue track: auto-advance at the segment boundary and report time
        # relative to the segment so the UI shows per-track position/length.
        if self._seg_end > self._seg_start and not self._seg_pending_seek:
            if time_ms >= self._seg_end:
                # Consume this segment boundary so we don't re-emit on the
                # next poll if playback is stopped (end of playlist) and the
                # backend still reports a time near the boundary. When a next
                # track exists, play_row() re-arms _seg_start/_seg_end.
                self._seg_end = 0
                self.playback_ended.emit()
                return
        if self._seg_start > 0 or self._seg_end > 0:
            seg_len = (
                self._seg_end - self._seg_start
                if self._seg_end > self._seg_start
                else max(0, length - self._seg_start)
            )
            rel = max(0, time_ms - self._seg_start)
            self.position_changed.emit(rel, seg_len)
        else:
            self.position_changed.emit(time_ms, length)

    # -- lifecycle ---------------------------------------------------------

    def shutdown(self) -> None:
        self._timer.stop()
        self._backend.release()


def _clamp_rate(rate: float) -> float:
    return max(RATE_MIN, min(RATE_MAX, float(rate)))
