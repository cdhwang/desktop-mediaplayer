"""Main application window.

Layout: a horizontal splitter with the central display area on the left
and the playlist panel on the right; the control bar sits along the
bottom. The central display becomes a stacked widget in Task 6, and a
menu bar / theming arrive in Task 15.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from desktop_music.constants import APP_NAME, MEDIA_EXTENSIONS, is_media, load_app_icon
from desktop_music.core.controller import PlayerController, VOLUME_STEP
from desktop_music.core.playlist import PlaylistModel, scan_dir_flat
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
        initial_media: list[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(APP_NAME)
        _icon = load_app_icon()
        if not _icon.isNull():
            self.setWindowIcon(_icon)
        self.resize(1100, 720)
        self.setMinimumSize(800, 480)

        self._settings = settings or SettingsStore()
        self._controller = controller or PlayerController(parent=self)
        self._playlist = PlaylistModel(self)
        self._controller.set_playlist(self._playlist)
        self._equalizer = EqualizerService(self._controller.backend)
        self._auto_hide_timer: QTimer | None = None
        # menu action created in _build_menu; declared here for early access
        self._act_normalize = None
        # OSD stays suppressed until startup wiring + state restore finish, so
        # programmatic volume/rate changes on launch don't flash the overlay.
        self._osd_ready = False
        self._shortcuts = ShortcutManager(self, self.dispatch_command)

        self._build_ui()
        self._connect()
        self._restore_state()
        self._shortcuts.rebind_all()
        # from here on, volume/seek/rate changes come from real user actions
        self._osd_ready = True

        # Enter / Return toggles fullscreen. This is a fixed binding (separate
        # from the customizable F shortcut) covering both the main Return key
        # and the numeric-keypad Enter.
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(self.toggle_fullscreen)

        if initial_media:
            self._open_initial_media(initial_media)

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
        # On Windows the central display promotes to a *native* window (for
        # libVLC video embedding). Native child windows don't repaint smoothly
        # during a live splitter drag — the handle appears to "jump" and snap
        # to discrete positions. Deferring the actual resize until the drag is
        # released keeps the interaction smooth on every platform (on Linux
        # opaque resizing already works, so this is a harmless no-op there).
        self._splitter.setOpaqueResize(False)
        self._splitter.setChildrenCollapsible(False)

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
        # No menu bar: every entry is reachable via the playback-area context
        # menu and the control bar's hamburger button. Hide the (empty) bar
        # QMainWindow creates by default so it doesn't take up any space.
        self.menuBar().hide()

    def _build_menu(self) -> None:
        from PyQt6.QtGui import QAction, QKeySequence
        from PyQt6.QtWidgets import QMenu

        from desktop_music.core import commands as cmd

        def shortcut(cid: str) -> QKeySequence:
            return QKeySequence(self._shortcuts.shortcut_for(cid))

        def set_menu_shortcut(action: "QAction", cid: str) -> None:
            """Show a command's key as a menu hint without binding it.

            Actual key handling is owned by :class:`ShortcutManager` (window
            scoped). Using ``WidgetShortcut`` context here makes the sequence
            display next to the menu item without registering a second,
            window-level binding — which would otherwise trigger Qt's
            "Ambiguous shortcut overload" and disable the key entirely.
            """
            action.setShortcut(shortcut(cid))
            action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)

        # The app has no menu bar; all entries live in a single context menu
        # (right-click the playback area) and the control bar's hamburger
        # button. Each top-level group is a QMenu owned by the window so it
        # can be re-added to the context menu on every pop-up.

        # -- File --
        file_menu = QMenu("&File", self)
        act_open = QAction("Open Files\u2026", self)
        act_open.triggered.connect(self._open_files_dialog)
        act_folder = QAction("Add Folder\u2026", self)
        act_folder.triggered.connect(self._open_folder_dialog)
        act_sub = QAction("Load Subtitle\u2026", self)
        act_sub.triggered.connect(self.open_subtitle_dialog)
        act_snap = QAction("Take Snapshot", self)
        set_menu_shortcut(act_snap, cmd.SNAPSHOT)
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
        view_menu = QMenu("&View", self)
        act_art = QAction("Album Art", self)
        act_art.triggered.connect(self.show_album_art)
        act_spec = QAction("Spectrum", self)
        act_spec.triggered.connect(self.show_spectrum)
        act_lyrics = QAction("Lyrics", self)
        act_lyrics.triggered.connect(self.show_lyrics)
        act_fs = QAction("Toggle Fullscreen", self)
        set_menu_shortcut(act_fs, cmd.FULLSCREEN)
        act_fs.triggered.connect(self.toggle_fullscreen)
        view_menu.addAction(act_art)
        view_menu.addAction(act_spec)
        view_menu.addAction(act_lyrics)
        view_menu.addSeparator()
        view_menu.addAction(act_fs)

        # -- Playback --
        pb_menu = QMenu("&Playback", self)
        for label, cid in (
            ("Play / Pause", cmd.PLAY_PAUSE),
            ("Stop", cmd.STOP),
            ("Next", cmd.NEXT),
            ("Previous", cmd.PREVIOUS),
        ):
            action = QAction(label, self)
            set_menu_shortcut(action, cid)
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
        # Audio normalizer (normvol) — checkable on/off toggle.
        self._act_normalize = QAction("Audio Normalizer", self)
        self._act_normalize.setCheckable(True)
        self._act_normalize.setChecked(self._controller.normalize)
        self._act_normalize.toggled.connect(self.toggle_normalize)
        pb_menu.addAction(self._act_normalize)

        # -- Tools --
        tools_menu = QMenu("&Tools", self)
        act_keys = QAction("Keyboard Shortcuts\u2026", self)
        act_keys.triggered.connect(self.open_shortcut_dialog)
        tools_menu.addAction(act_keys)

        # keep the group menus for assembling the pop-up menu on demand
        self._menu_groups: list[QMenu] = [
            file_menu,
            view_menu,
            pb_menu,
            tools_menu,
        ]

    def _build_main_menu(self) -> "QMenu":
        """Assemble the consolidated pop-up menu from the group menus."""
        from PyQt6.QtWidgets import QMenu

        popup = QMenu(self)
        for group in self._menu_groups:
            popup.addMenu(group)
        return popup

    def _show_main_menu(self) -> None:
        """Pop up the consolidated menu at the cursor.

        Used by the control bar's hamburger button and (via
        :meth:`_show_context_menu`) by right-clicking the playback area.
        Mirrors PotPlayer, which exposes every entry from one menu.
        """
        from PyQt6.QtGui import QCursor

        self._build_main_menu().exec(QCursor.pos())

    def _show_context_menu(self, global_pos) -> None:
        """Pop up the consolidated menu at *global_pos* (a right-click)."""
        self._build_main_menu().exec(global_pos)

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
        ctrl.volume_changed.connect(self._on_volume_osd)
        ctrl.seeked.connect(self._on_seeked_osd)
        ctrl.rate_changed.connect(self._on_rate_osd)
        ctrl.play_mode_changed.connect(self._on_play_mode_changed)
        ctrl.media_changed.connect(self._on_media_changed)
        ctrl.normalize_changed.connect(self._on_normalize_changed)

        # When the backend is rebuilt (normalizer toggle), re-point the
        # equalizer at the new player and re-attach video output.
        ctrl.set_backend_rebuilt_hook(self._on_backend_rebuilt)

        panel.track_activated.connect(ctrl.play_row)
        panel.add_files_requested.connect(self._open_files_dialog)
        panel.add_folder_requested.connect(self._open_folder_dialog)
        self._playlist.current_changed.connect(panel.highlight_current)

        self._central_display.video.double_clicked.connect(self.toggle_fullscreen)
        self._central_display.double_clicked.connect(ctrl.toggle_pause)
        self._central_display.context_menu_requested.connect(self._show_context_menu)
        self._central_display.paths_dropped.connect(self._on_paths_dropped_play)
        self._central_display.volume_step.connect(
            lambda steps: ctrl.change_volume(steps * VOLUME_STEP)
        )
        panel.paths_dropped.connect(self._on_paths_dropped_add)

        # initialize volume display from backend
        ctrl.set_volume(cb._volume_slider.value())

    # -- file dialogs ------------------------------------------------------

    def _open_initial_media(self, args: list[str]) -> None:
        """Handle media given as command-line arguments.

        The playlist is (re)populated with every playable file in the
        directory of the first argument, and playback starts on that file.
        Directories passed as arguments are added recursively; the first
        playable track found is played.
        """
        import os

        from desktop_music.services.cue import is_cue

        first = args[0]
        if os.path.isdir(first):
            self._playlist.clear()
            added = self._playlist.add_paths(args)
            if added > 0:
                self._controller.play_row(0)
            return

        if not os.path.isfile(first):
            return

        # A cue sheet given directly expands into its referenced media files;
        # the cue file itself is never added. Play the first expanded track.
        if is_cue(first):
            self._playlist.clear()
            added = self._playlist.add_paths(args)
            if added > 0:
                self._controller.play_row(0)
            return

        directory = os.path.dirname(os.path.abspath(first)) or "."
        siblings = scan_dir_flat(directory)
        target = os.path.abspath(first)
        # ensure the requested file is present even if its extension check
        # or the directory scan somehow missed it
        if target not in siblings and is_media(target):
            siblings.append(target)
            siblings.sort()

        self._playlist.clear()
        self._playlist.add_paths(siblings)
        try:
            row = siblings.index(target)
        except ValueError:
            row = 0
        self._controller.play_row(row)

    def _open_files_dialog(self) -> None:
        from desktop_music.services.cue import CUE_EXTENSION

        exts = sorted(MEDIA_EXTENSIONS | {CUE_EXTENSION})
        patterns = " ".join(f"*{ext}" for ext in exts)
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

    def _on_paths_dropped_add(self, paths: list, row: int = -1) -> None:
        """Files/folders dropped on the playlist: insert at the drop position.

        ``row`` is the source row to insert before; ``-1`` appends at the end.
        Playback is not interrupted.
        """
        if row < 0:
            self._playlist.add_paths(list(paths))
        else:
            self._playlist.insert_paths(row, list(paths))

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

    # -- OSD (transient on-screen status) ---------------------------------

    def _on_volume_osd(self, volume: int, muted: bool) -> None:
        if not self._osd_ready:
            return
        if muted:
            self._central_display.show_osd("Muted")
        else:
            self._central_display.show_osd(f"Volume  {volume}%")

    def _on_seeked_osd(self, position_ms: int, length_ms: int) -> None:
        from desktop_music.core.formatting import format_ms

        if not self._osd_ready:
            return
        if length_ms > 0:
            self._central_display.show_osd(
                f"{format_ms(position_ms)} / {format_ms(length_ms)}"
            )
        else:
            self._central_display.show_osd(format_ms(position_ms))

    def _on_rate_osd(self, rate: float) -> None:
        if not self._osd_ready:
            return
        self._central_display.show_osd(f"Speed  {rate:.2f}x")

    # -- audio normalizer --------------------------------------------------

    def toggle_normalize(self, enabled: bool) -> None:
        """Enable/disable the audio normalizer (from the menu action)."""
        self._controller.set_normalize(enabled)

    def _on_backend_rebuilt(self, backend) -> None:
        """Re-wire services to a freshly created backend.

        Called by the controller after it rebuilds the backend (normalizer
        toggle). Re-points the equalizer and re-attaches video output if a
        video is currently showing.
        """
        self._equalizer.rebind(backend)
        if self._central_display.current_page() == "video":
            surface = self._central_display.video
            backend.set_video_window(surface.native_window_id())

    def _on_normalize_changed(self, enabled: bool) -> None:
        if hasattr(self, "_act_normalize") and self._act_normalize is not None:
            self._act_normalize.setChecked(enabled)
        if not self._osd_ready:
            return
        self._central_display.show_osd(
            "Normalizer  On" if enabled else "Normalizer  Off"
        )

    def _on_media_changed(self, path) -> None:
        """Extract metadata for the current media and update the display."""
        import os

        if not path:
            self._central_display.clear_metadata()
            self.setWindowTitle(APP_NAME)
            return
        meta = read_metadata(path)
        fallback = os.path.basename(path)
        from desktop_music.constants import is_audio, is_video

        # For cue tracks several playlist entries share one backing file, so
        # file-level tags are identical for all of them. Prefer the current
        # playlist track's own title/artist (parsed from the cue sheet) so the
        # now-playing display matches the playlist item and updates on every
        # track change — even when the backing file didn't change.
        current_track = self._playlist.current_track()
        if current_track is not None and current_track.is_cue_track:
            import dataclasses

            meta = dataclasses.replace(
                meta,
                title=current_track.title or meta.title,
                artist=current_track.artist or meta.artist,
            )
            fallback = current_track.display_title

        # Reflect the now-playing track in the window title. Prefer
        # "Title - Artist"; fall back to the file name / cue display title
        # when tags are missing, then append the app name.
        self.setWindowTitle(self._format_window_title(meta, fallback))

        if is_video(path):
            # embed video output into the native surface and show it.
            # Promoting the surface to a native window and switching the
            # stacked page can nudge the splitter on Windows, so snapshot the
            # splitter sizes and restore them after the switch to keep the
            # playback/playlist divide exactly where the user left it.
            saved_sizes = self._splitter.sizes()
            surface = self._central_display.video
            self._controller.backend.set_video_window(surface.native_window_id())
            self._central_display.show_page("video")
            self._central_display.spectrum.stop()
            self._splitter.setSizes(saved_sizes)
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

    @staticmethod
    def _format_window_title(meta, fallback: str) -> str:
        """Build the window title for the now-playing track.

        Prefer "Title - Artist" from tags, falling back to *fallback* (the
        file name or cue display title) when the title tag is missing. The
        app name is always appended so the window stays identifiable.
        """
        title = (meta.title or "").strip() or fallback.strip()
        artist = (meta.artist or "").strip()
        label = f"{title} - {artist}" if title and artist else title
        return f"{label} \u2014 {APP_NAME}" if label else APP_NAME

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
        normalize = data.get("normalize")
        if isinstance(normalize, bool) and normalize:
            # Rebuild the backend with the normalizer enabled. The equalizer
            # was just applied to the *current* backend; set_normalize's
            # rebuild hook re-applies it to the new one.
            self._controller.set_normalize(True)
        if self._act_normalize is not None:
            self._act_normalize.setChecked(self._controller.normalize)
        self._shortcuts.load_state(data.get("shortcuts", {}))
        self._on_play_mode_changed()

    def _save_state(self) -> None:
        self._settings.update(
            {
                "playlist": self._playlist.to_state(),
                "play_mode": self._controller.play_mode.to_state(),
                "volume": self._controller.volume,
                "eq_preset": self._equalizer.preset_index,
                "normalize": self._controller.normalize,
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
