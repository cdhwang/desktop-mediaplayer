"""Main application window.

Layout: a horizontal splitter with the central display area on the left
and the playlist panel on the right; the control bar sits along the
bottom. The central display becomes a stacked widget in Task 6, and a
menu bar / theming arrive in Task 15.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from desktop_music.constants import APP_NAME, MEDIA_EXTENSIONS
from desktop_music.core.controller import PlayerController
from desktop_music.core.playlist import PlaylistModel
from desktop_music.core.shortcuts import ShortcutManager
from desktop_music.services.backend import PlaybackState
from desktop_music.services.equalizer import PRESET_NONE, EqualizerService
from desktop_music.services.lyrics import read_lyrics
from desktop_music.services.metadata import read_metadata
from desktop_music.services.settings import SettingsStore
from desktop_music.ui.central_display import CentralDisplay
from desktop_music.ui.control_bar import ControlBar
from desktop_music.ui.playlist_panel import PlaylistPanel

# how long the control bar stays visible after mouse movement in fullscreen
_FULLSCREEN_HIDE_MS = 2500


class MainWindow(QMainWindow):
    """Top-level window for the media player."""

    def __init__(
        self,
        controller: PlayerController | None = None,
        settings: SettingsStore | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(APP_NAME)
        self.resize(1100, 720)
        self.setMinimumSize(800, 480)

        self._settings = settings or SettingsStore()
        self._controller = controller or PlayerController(parent=self)
        self._playlist = PlaylistModel(self)
        self._controller.set_playlist(self._playlist)
        self._equalizer = EqualizerService(self._controller.backend)
        self._auto_hide_timer: QTimer | None = None
        self._shortcuts = ShortcutManager(self, self.dispatch_command)

        self._build_ui()
        self._connect()
        self._restore_state()
        self._shortcuts.rebind_all()

    @property
    def controller(self) -> PlayerController:
        return self._controller

    @property
    def playlist(self) -> PlaylistModel:
        return self._playlist

    @property
    def equalizer(self) -> EqualizerService:
        return self._equalizer

    @property
    def shortcuts(self) -> ShortcutManager:
        return self._shortcuts

    def dispatch_command(self, command_id: str) -> None:
        """Route a named command to the right handler (window or controller)."""
        from desktop_music.core import commands as cmd

        if command_id == cmd.FULLSCREEN:
            self.toggle_fullscreen()
        elif command_id == cmd.SNAPSHOT:
            self.take_snapshot()
        else:
            self._controller.dispatch(command_id)

    def open_shortcut_dialog(self) -> None:
        from desktop_music.ui.shortcut_dialog import ShortcutDialog

        dialog = ShortcutDialog(self._shortcuts, self)
        dialog.shortcuts_changed.connect(self._save_state)
        dialog.exec()

    def open_equalizer_dialog(self) -> None:
        from desktop_music.ui.equalizer_dialog import EqualizerDialog

        dialog = EqualizerDialog(self._equalizer, self)
        dialog.preset_selected.connect(self._on_eq_preset_selected)
        dialog.exec()

    def _on_eq_preset_selected(self, index: int) -> None:
        self._settings.set("eq_preset", index)

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left column: the display area with the control bar stacked *below*
        # it, so the seek/volume bar only spans the playback area — not the
        # playlist (matching PotPlayer).
        self._central_display = CentralDisplay()
        self._control_bar = ControlBar()

        left_column = QWidget()
        left_layout = QVBoxLayout(left_column)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_layout.addWidget(self._central_display, stretch=1)
        left_layout.addWidget(self._control_bar)
        self._splitter.addWidget(left_column)

        self._playlist_panel = PlaylistPanel(self._playlist)
        self._splitter.addWidget(self._playlist_panel)
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 0)
        self._splitter.setSizes([760, 300])

        layout.addWidget(self._splitter, stretch=1)

        self.setCentralWidget(central)

        self._build_menu()

    def _build_menu(self) -> None:
        from PyQt6.QtGui import QAction, QKeySequence

        from desktop_music.core import commands as cmd

        menubar = self.menuBar()

        def shortcut(cid: str) -> QKeySequence:
            return QKeySequence(self._shortcuts.shortcut_for(cid))

        # -- File --
        file_menu = menubar.addMenu("&File")
        act_open = QAction("Open Files\u2026", self)
        act_open.triggered.connect(self._open_files_dialog)
        act_folder = QAction("Add Folder\u2026", self)
        act_folder.triggered.connect(self._open_folder_dialog)
        act_sub = QAction("Load Subtitle\u2026", self)
        act_sub.triggered.connect(self.open_subtitle_dialog)
        act_snap = QAction("Take Snapshot", self)
        act_snap.setShortcut(shortcut(cmd.SNAPSHOT))
        act_snap.triggered.connect(self.take_snapshot)
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_open)
        file_menu.addAction(act_folder)
        file_menu.addSeparator()
        file_menu.addAction(act_sub)
        file_menu.addAction(act_snap)
        file_menu.addSeparator()
        file_menu.addAction(act_quit)

        # -- View --
        view_menu = menubar.addMenu("&View")
        act_art = QAction("Album Art", self)
        act_art.triggered.connect(self.show_album_art)
        act_spec = QAction("Spectrum", self)
        act_spec.triggered.connect(self.show_spectrum)
        act_lyrics = QAction("Lyrics", self)
        act_lyrics.triggered.connect(self.show_lyrics)
        act_fs = QAction("Toggle Fullscreen", self)
        act_fs.setShortcut(shortcut(cmd.FULLSCREEN))
        act_fs.triggered.connect(self.toggle_fullscreen)
        view_menu.addAction(act_art)
        view_menu.addAction(act_spec)
        view_menu.addAction(act_lyrics)
        view_menu.addSeparator()
        view_menu.addAction(act_fs)

        # -- Playback --
        pb_menu = menubar.addMenu("&Playback")
        for label, cid in (
            ("Play / Pause", cmd.PLAY_PAUSE),
            ("Stop", cmd.STOP),
            ("Next", cmd.NEXT),
            ("Previous", cmd.PREVIOUS),
        ):
            action = QAction(label, self)
            action.setShortcut(shortcut(cid))
            action.triggered.connect(lambda _checked=False, c=cid: self.dispatch_command(c))
            pb_menu.addAction(action)
        pb_menu.addSeparator()
        # speed submenu
        speed_menu = pb_menu.addMenu("Speed")
        for label, rate in (("0.5x", 0.5), ("1.0x", 1.0), ("1.5x", 1.5), ("2.0x", 2.0)):
            action = QAction(label, self)
            action.triggered.connect(lambda _checked=False, r=rate: self.set_rate(r))
            speed_menu.addAction(action)
        # dynamic audio/subtitle track menus
        self._audio_menu = pb_menu.addMenu("Audio Track")
        self._audio_menu.aboutToShow.connect(self._populate_audio_menu)
        self._subtitle_menu = pb_menu.addMenu("Subtitle Track")
        self._subtitle_menu.aboutToShow.connect(self._populate_subtitle_menu)
        pb_menu.addSeparator()
        act_eq = QAction("Equalizer\u2026", self)
        act_eq.triggered.connect(self.open_equalizer_dialog)
        pb_menu.addAction(act_eq)

        # -- Tools --
        tools_menu = menubar.addMenu("&Tools")
        act_keys = QAction("Keyboard Shortcuts\u2026", self)
        act_keys.triggered.connect(self.open_shortcut_dialog)
        tools_menu.addAction(act_keys)

    def _show_main_menu(self) -> None:
        """Pop up a consolidated menu at the control bar's menu button.

        Mirrors PotPlayer's hamburger button, which exposes the same
        entries as the top menu bar.
        """
        from PyQt6.QtGui import QCursor

        menu = self.menuBar()
        # QMenuBar can't be popped up directly; build a transient QMenu.
        from PyQt6.QtWidgets import QMenu

        popup = QMenu(self)
        for action in menu.actions():
            if action.menu():
                popup.addMenu(action.menu())
        popup.exec(QCursor.pos())

    def _populate_audio_menu(self) -> None:
        from PyQt6.QtGui import QAction

        self._audio_menu.clear()
        for track_id, name in self.audio_track_items():
            action = QAction(name, self)
            action.triggered.connect(
                lambda _checked=False, tid=track_id: self.select_audio_track(tid)
            )
            self._audio_menu.addAction(action)

    def _populate_subtitle_menu(self) -> None:
        from PyQt6.QtGui import QAction

        self._subtitle_menu.clear()
        for track_id, name in self.subtitle_track_items():
            action = QAction(name, self)
            action.triggered.connect(
                lambda _checked=False, tid=track_id: self.select_subtitle_track(tid)
            )
            self._subtitle_menu.addAction(action)

    def _connect(self) -> None:
        cb = self._control_bar
        ctrl = self._controller
        panel = self._playlist_panel

        cb.play_pause_clicked.connect(ctrl.toggle_pause)
        cb.stop_clicked.connect(ctrl.stop)
        cb.next_clicked.connect(ctrl.next)
        cb.previous_clicked.connect(ctrl.previous)
        cb.mute_clicked.connect(ctrl.toggle_mute)
        cb.seek_requested.connect(ctrl.seek_to_fraction)
        cb.volume_changed.connect(ctrl.set_volume)
        cb.fullscreen_clicked.connect(self.toggle_fullscreen)
        cb.shuffle_clicked.connect(ctrl.toggle_shuffle)
        cb.repeat_clicked.connect(ctrl.cycle_repeat)
        cb.eject_clicked.connect(self._open_files_dialog)
        cb.settings_clicked.connect(self.open_equalizer_dialog)
        cb.menu_clicked.connect(self._show_main_menu)

        ctrl.position_changed.connect(cb.set_position)
        ctrl.position_changed.connect(self._on_position_changed)
        ctrl.state_changed.connect(self._on_state_changed)
        ctrl.volume_changed.connect(cb.set_volume_display)
        ctrl.play_mode_changed.connect(self._on_play_mode_changed)
        ctrl.media_changed.connect(self._on_media_changed)

        panel.track_activated.connect(ctrl.play_row)
        panel.add_files_requested.connect(self._open_files_dialog)
        panel.add_folder_requested.connect(self._open_folder_dialog)
        self._playlist.current_changed.connect(panel.highlight_current)

        self._central_display.video.double_clicked.connect(self.toggle_fullscreen)
        self._central_display.paths_dropped.connect(self._on_paths_dropped_play)
        panel.paths_dropped.connect(self._on_paths_dropped_add)

        # initialize volume display from backend
        ctrl.set_volume(cb._volume_slider.value())

    # -- file dialogs ------------------------------------------------------

    def _open_files_dialog(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in sorted(MEDIA_EXTENSIONS))
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add Media Files", "", f"Media Files ({patterns});;All Files (*)"
        )
        if paths:
            self._playlist.add_paths(paths)

    def _open_folder_dialog(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Add Folder")
        if directory:
            self._playlist.add_paths([directory])

    # -- drag & drop -------------------------------------------------------

    def _on_paths_dropped_add(self, paths: list) -> None:
        """Files/folders dropped on the playlist: append without interrupting."""
        self._playlist.add_paths(list(paths))

    def _on_paths_dropped_play(self, paths: list) -> None:
        """Files/folders dropped on the playback area: append and play the first."""
        first_new_row = self._playlist.rowCount()
        added = self._playlist.add_paths(list(paths))
        if added > 0:
            self._controller.play_row(first_new_row)

    # -- state handling ----------------------------------------------------

    def _on_state_changed(self, state: PlaybackState) -> None:
        self._control_bar.set_playing(state == PlaybackState.PLAYING)

    def _on_position_changed(self, position_ms: int, length_ms: int) -> None:
        self._central_display.spectrum.set_position(position_ms)
        self._central_display.set_now_playing_time(position_ms, length_ms)

    def _on_media_changed(self, path) -> None:
        """Extract metadata for the current media and update the display."""
        import os

        if not path:
            self._central_display.clear_metadata()
            return
        meta = read_metadata(path)
        fallback = os.path.basename(path)
        from desktop_music.constants import is_audio, is_video

        if is_video(path):
            # embed video output into the native surface and show it
            surface = self._central_display.video
            self._controller.backend.set_video_window(surface.native_window_id())
            self._central_display.show_page("video")
            self._central_display.spectrum.stop()
        else:
            self._central_display.show_page("album_art")
            self._central_display.show_metadata(meta, fallback_title=fallback)
            self._central_display.set_lyrics(read_lyrics(path))
            if is_audio(path):
                self._central_display.spectrum.analyze(path)
                self._central_display.spectrum.start()
            else:
                self._central_display.spectrum.stop()
        # enrich the playlist row so the list shows nice titles
        row = self._playlist.current_index
        if row >= 0:
            self._playlist.update_track_metadata(
                row,
                title=meta.title,
                artist=meta.artist,
                album=meta.album,
                duration_ms=meta.duration_ms,
            )

    def show_lyrics(self) -> None:
        """Switch the central display to the lyrics page."""
        self._central_display.show_page("lyrics")

    def show_album_art(self) -> None:
        """Switch the central display to the album-art page."""
        self._central_display.show_page("album_art")

    def show_spectrum(self) -> None:
        """Switch the central display to the spectrum page."""
        self._central_display.show_page("spectrum")
        self._central_display.spectrum.start()

    def _on_play_mode_changed(self) -> None:
        pm = self._controller.play_mode
        self._control_bar.set_play_mode_display(pm.shuffle, pm.repeat.value)

    # -- persistence -------------------------------------------------------

    def _restore_state(self) -> None:
        data = self._settings.load()
        self._playlist.load_state(data.get("playlist", {}))
        self._controller.play_mode.load_state(data.get("play_mode", {}))
        volume = data.get("volume")
        if isinstance(volume, int):
            self._controller.set_volume(volume)
        eq_preset = data.get("eq_preset", PRESET_NONE)
        if isinstance(eq_preset, int):
            self._equalizer.apply_preset(eq_preset)
        self._shortcuts.load_state(data.get("shortcuts", {}))
        self._on_play_mode_changed()

    def _save_state(self) -> None:
        self._settings.update(
            {
                "playlist": self._playlist.to_state(),
                "play_mode": self._controller.play_mode.to_state(),
                "volume": self._controller.backend.get_volume(),
                "eq_preset": self._equalizer.preset_index,
                "shortcuts": self._shortcuts.to_state(),
            }
        )
        try:
            self._settings.save()
        except OSError:
            pass

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self._exit_fullscreen()
        else:
            self._enter_fullscreen()

    def _enter_fullscreen(self) -> None:
        self.showFullScreen()
        self.setMouseTracking(True)
        # hide chrome; a timer re-hides after mouse activity
        self._control_bar.hide()
        self._playlist_panel.hide()
        if self._auto_hide_timer is None:
            self._auto_hide_timer = QTimer(self)
            self._auto_hide_timer.setSingleShot(True)
            self._auto_hide_timer.timeout.connect(self._hide_chrome)

    def _exit_fullscreen(self) -> None:
        if self._auto_hide_timer is not None:
            self._auto_hide_timer.stop()
        self.setMouseTracking(False)
        self.showNormal()
        self._control_bar.show()
        self._playlist_panel.show()

    def _hide_chrome(self) -> None:
        if self.isFullScreen():
            self._control_bar.hide()
            self._playlist_panel.hide()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self.isFullScreen():
            # reveal chrome, then schedule auto-hide
            self._control_bar.show()
            if self._auto_hide_timer is not None:
                self._auto_hide_timer.start(_FULLSCREEN_HIDE_MS)
        super().mouseMoveEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # Esc leaves fullscreen (F toggles via shortcut in Task 14)
        if event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self._exit_fullscreen()
            return
        super().keyPressEvent(event)

    # -- audio / subtitle track menus -------------------------------------

    def audio_track_items(self) -> list[tuple[int, str]]:
        return self._controller.backend.audio_tracks()

    def subtitle_track_items(self) -> list[tuple[int, str]]:
        return self._controller.backend.subtitle_tracks()

    def select_audio_track(self, track_id: int) -> None:
        self._controller.backend.set_audio_track(track_id)

    def select_subtitle_track(self, track_id: int) -> None:
        self._controller.backend.set_subtitle_track(track_id)

    # -- external subtitles / snapshot / rate -----------------------------

    def open_subtitle_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Subtitle", "", "Subtitles (*.srt *.ass *.ssa *.sub);;All Files (*)"
        )
        if path:
            self._controller.backend.add_subtitle_file(path)

    def take_snapshot(self) -> str:
        """Save a snapshot of the current video frame; returns the path or ""."""
        import os
        import time

        default = os.path.join(
            os.path.expanduser("~"), f"snapshot-{int(time.time())}.png"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Snapshot", default, "PNG Image (*.png)"
        )
        if not path:
            return ""
        ok = self._controller.backend.take_snapshot(path)
        return path if ok else ""

    def set_rate(self, rate: float) -> None:
        self._controller.set_rate(rate)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._save_state()
        self._central_display.spectrum.closeEvent(event)
        self._controller.shutdown()
        super().closeEvent(event)
