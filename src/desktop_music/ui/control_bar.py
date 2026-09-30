"""Bottom control bar (PotPlayer-style, two rows).

Row 1: the seek slider spanning the full width, with the volume slider at
       the far right.
Row 2: transport buttons on the left (play/pause, stop, previous, next,
       eject), the elapsed / total time in the middle, and settings +
       menu buttons on the right. Shuffle/repeat live on the settings row
       too, mirroring PotPlayer's compact transport strip.

The bar stays "dumb": it emits intent signals and exposes display setters;
the main window wires it to the controller.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from desktop_music.core.formatting import format_ms


class ControlBar(QWidget):
    """Playback control strip shown at the bottom of the window."""

    play_pause_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    next_clicked = pyqtSignal()
    previous_clicked = pyqtSignal()
    eject_clicked = pyqtSignal()
    fullscreen_clicked = pyqtSignal()
    mute_clicked = pyqtSignal()
    shuffle_clicked = pyqtSignal()
    repeat_clicked = pyqtSignal()
    settings_clicked = pyqtSignal()
    menu_clicked = pyqtSignal()
    # user dragged/clicked the seek bar to a fraction 0.0..1.0
    seek_requested = pyqtSignal(float)
    # user changed volume to 0..100
    volume_changed = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("controlBar")
        self._length_ms = 0
        self._seeking = False
        self._build_ui()

    def _build_ui(self) -> None:
        # ---- Row 1: seek slider + volume -------------------------------
        self._seek_slider = QSlider(Qt.Orientation.Horizontal)
        self._seek_slider.setObjectName("seekSlider")
        self._seek_slider.setRange(0, 1000)  # per-mille of total length
        self._seek_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._seek_slider.sliderPressed.connect(self._on_seek_pressed)
        self._seek_slider.sliderReleased.connect(self._on_seek_released)

        self._mute_btn = QPushButton("\U0001f50a")
        self._mute_btn.setObjectName("iconButton")
        self._mute_btn.setFixedWidth(28)
        self._mute_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._mute_btn.clicked.connect(self.mute_clicked)

        self._volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._volume_slider.setObjectName("volumeSlider")
        self._volume_slider.setRange(0, 100)
        self._volume_slider.setValue(80)
        self._volume_slider.setFixedWidth(90)
        self._volume_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._volume_slider.valueChanged.connect(self.volume_changed)

        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(6)
        row1.addWidget(self._seek_slider, stretch=1)
        row1.addWidget(self._mute_btn)
        row1.addWidget(self._volume_slider)

        # ---- Row 2: transport | time | settings ------------------------
        self._play_btn = self._icon_btn("\u25b6", self.play_pause_clicked)
        self._stop_btn = self._icon_btn("\u23f9", self.stop_clicked)
        self._prev_btn = self._icon_btn("\u23ee", self.previous_clicked)
        self._next_btn = self._icon_btn("\u23ed", self.next_clicked)
        self._eject_btn = self._icon_btn("\u23cf", self.eject_clicked)

        self._time_lbl = QLabel("00:00:00 / 00:00:00")
        self._time_lbl.setObjectName("timeLabel")

        self._shuffle_btn = self._icon_btn("\U0001f500", self.shuffle_clicked)
        self._repeat_btn = self._icon_btn("\U0001f501", self.repeat_clicked)
        self._shuffle_btn.setCheckable(True)
        self._repeat_btn.setCheckable(True)
        self._settings_btn = self._icon_btn("\u2699", self.settings_clicked)
        self._menu_btn = self._icon_btn("\u2630", self.menu_clicked)
        self._fullscreen_btn = self._icon_btn("\u26f6", self.fullscreen_clicked)

        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(4)
        row2.addWidget(self._play_btn)
        row2.addWidget(self._stop_btn)
        row2.addWidget(self._prev_btn)
        row2.addWidget(self._next_btn)
        row2.addWidget(self._eject_btn)
        row2.addSpacing(8)
        row2.addWidget(self._time_lbl)
        row2.addStretch(1)
        row2.addWidget(self._shuffle_btn)
        row2.addWidget(self._repeat_btn)
        row2.addWidget(self._fullscreen_btn)
        row2.addWidget(self._settings_btn)
        row2.addWidget(self._menu_btn)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 4, 8, 6)
        outer.setSpacing(4)
        outer.addLayout(row1)
        outer.addLayout(row2)

    def _icon_btn(self, glyph: str, signal) -> QPushButton:
        btn = QPushButton(glyph)
        btn.setObjectName("iconButton")
        btn.setFixedWidth(34)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.clicked.connect(signal)
        return btn

    # -- display setters (called by controller/window) ---------------------

    def set_position(self, position_ms: int, length_ms: int) -> None:
        """Update the seek slider and the combined time label."""
        self._length_ms = length_ms
        self._time_lbl.setText(
            f"{format_ms(position_ms)} / {format_ms(length_ms)}"
        )
        if not self._seeking:
            if length_ms > 0:
                permille = int(1000 * position_ms / length_ms)
                self._seek_slider.setValue(max(0, min(1000, permille)))
            else:
                self._seek_slider.setValue(0)

    def set_playing(self, playing: bool) -> None:
        self._play_btn.setText("\u23f8" if playing else "\u25b6")

    def set_volume_display(self, volume: int, muted: bool) -> None:
        self._volume_slider.blockSignals(True)
        self._volume_slider.setValue(volume)
        self._volume_slider.blockSignals(False)
        self._mute_btn.setText("\U0001f507" if muted else "\U0001f50a")

    def set_play_mode_display(self, shuffle: bool, repeat: str) -> None:
        self._shuffle_btn.setChecked(shuffle)
        self._repeat_btn.setChecked(repeat != "none")
        marker = {"none": "\U0001f501", "all": "\U0001f501", "one": "\U0001f502"}
        self._repeat_btn.setText(marker.get(repeat, "\U0001f501"))
        self._repeat_btn.setToolTip(f"Repeat: {repeat}")

    # -- seek slider interaction ------------------------------------------

    def _on_seek_pressed(self) -> None:
        self._seeking = True

    def _on_seek_released(self) -> None:
        self._seeking = False
        fraction = self._seek_slider.value() / 1000.0
        self.seek_requested.emit(fraction)
