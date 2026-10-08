"""Album-art + now-playing view for audio tracks.

Mirrors PotPlayer's audio view: a large album-art area on top, and a
bottom "now-playing" overlay row showing the big elapsed/total time, the
track title, the technical info line (e.g. ``MP3 320kbps 44.1khz``), and a
small mini-spectrum on the right.
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QGridLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from desktop_music.core.formatting import format_ms
from desktop_music.services.metadata import Metadata
from desktop_music.ui.marquee_label import MarqueeLabel
from desktop_music.ui.spectrum_widget import MiniSpectrum

# Fraction of the shorter widget dimension used by the crisp foreground art,
# leaving a margin on every side where the blurred background shows through.
_FG_SCALE = 0.82
# How small to shrink the image before scaling it back up; smaller => blurrier.
# This downsample/upsample approach is backend-independent (works on Windows,
# unlike QGraphicsBlurEffect rendered to an offscreen pixmap).
_BLUR_DOWNSCALE = 0.02
# Number of smooth up/down passes; more passes => softer, heavier blur.
_BLUR_PASSES = 4
# Darken the blurred background so the foreground art stays prominent.
_BG_DIM = 110  # alpha of the black overlay drawn on top of the blur (0-255)


def _blur_pixmap(src: QPixmap) -> QPixmap:
    """Return a blurred copy of *src* using downscale/upscale passes.

    Uses only ``QPixmap.scaled`` so it renders identically across platforms,
    avoiding the ``QGraphicsBlurEffect`` offscreen-render issues seen on
    Windows.
    """
    if src.isNull():
        return src
    w, h = src.width(), src.height()
    small_w = max(1, int(w * _BLUR_DOWNSCALE))
    small_h = max(1, int(h * _BLUR_DOWNSCALE))

    result = src
    for _ in range(_BLUR_PASSES):
        small = result.scaled(
            small_w,
            small_h,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        result = small.scaled(
            w,
            h,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return result


class _ArtCanvas(QWidget):
    """Draws cover art centered over a blurred, zoom-to-fill background.

    Mirrors PotPlayer: the empty margins around aspect-fitted album art are
    filled with a heavily blurred, zoomed copy of the same artwork.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("albumArt")
        self.setMinimumSize(200, 200)
        self._source: QPixmap | None = None
        self._placeholder = "\u266a"
        self._blur_cache: QPixmap | None = None
        self._blur_cache_size = None

    def set_pixmap(self, pixmap: QPixmap | None) -> None:
        self._source = pixmap if pixmap and not pixmap.isNull() else None
        self._blur_cache = None
        self._blur_cache_size = None
        self.update()

    def has_pixmap(self) -> bool:
        return self._source is not None

    def _background(self) -> QPixmap | None:
        """Blurred, zoom-to-fill background sized to the widget."""
        if self._source is None:
            return None
        target = self.size()
        if self._blur_cache is not None and self._blur_cache_size == (
            target.width(),
            target.height(),
        ):
            return self._blur_cache

        # Scale the source to cover the whole widget (crop overflow), then blur.
        filled = self._source.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        # Center-crop to the exact widget size before blurring.
        x = max(0, (filled.width() - target.width()) // 2)
        y = max(0, (filled.height() - target.height()) // 2)
        cropped = filled.copy(x, y, target.width(), target.height())
        self._blur_cache = _blur_pixmap(cropped)
        self._blur_cache_size = (target.width(), target.height())
        return self._blur_cache

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        rect = self.rect()
        painter.fillRect(rect, QColor("#0b0b0e"))

        if self._source is None:
            painter.setPen(QColor("#3a3a44"))
            font = painter.font()
            font.setPixelSize(72)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._placeholder)
            painter.end()
            return

        # 1) blurred zoom-to-fill background.
        bg = self._background()
        if bg is not None:
            painter.drawPixmap(0, 0, bg)
            painter.fillRect(rect, QColor(0, 0, 0, _BG_DIM))

        # 2) crisp, aspect-fitted foreground, inset so a margin of the blurred
        #    background always shows on every side.
        box_w = int(rect.width() * _FG_SCALE)
        box_h = int(rect.height() * _FG_SCALE)
        fg = self._source.scaled(
            box_w,
            box_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        fx = (rect.width() - fg.width()) / 2
        fy = (rect.height() - fg.height()) / 2
        painter.drawPixmap(QPointF(fx, fy), fg)
        painter.end()


class AlbumArtView(QWidget):
    """Cover art with a PotPlayer-style now-playing overlay beneath it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()
        self.clear()

    def _build_ui(self) -> None:
        self._art = _ArtCanvas()

        # ---- now-playing overlay -------------------------------------
        self._elapsed = QLabel("00:00")
        self._elapsed.setObjectName("bigTime")
        self._elapsed.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._total = QLabel("00:00")
        self._total.setObjectName("bigTimeTotal")
        self._total.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        self._title = MarqueeLabel("")
        self._title.setObjectName("nowPlayingTitle")
        self._tech = QLabel("")
        self._tech.setObjectName("nowPlayingTech")

        self._mini = MiniSpectrum()

        overlay = QGridLayout()
        overlay.setContentsMargins(16, 8, 16, 8)
        overlay.setHorizontalSpacing(12)
        # column 0: stacked big time (elapsed over total)
        time_box = QVBoxLayout()
        time_box.setSpacing(0)
        time_box.addWidget(self._elapsed)
        time_box.addWidget(self._total)
        overlay.addLayout(time_box, 0, 0, 2, 1)
        # column 1: title + tech info
        overlay.addWidget(self._title, 0, 1)
        overlay.addWidget(self._tech, 1, 1)
        overlay.setColumnStretch(1, 1)
        # column 2: mini spectrum
        overlay.addWidget(self._mini, 0, 2, 2, 1)

        overlay_widget = QWidget()
        overlay_widget.setObjectName("nowPlayingBar")
        overlay_widget.setLayout(overlay)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._art, stretch=1)
        layout.addWidget(overlay_widget)

    # -- public API --------------------------------------------------------

    def clear(self) -> None:
        self._art.set_pixmap(None)
        self._title.setText("")
        self._tech.setText("")
        self._elapsed.setText("00:00")
        self._total.setText("00:00")

    def show_metadata(self, meta: Metadata, fallback_title: str = "") -> None:
        """Display *meta*, using *fallback_title* when the title tag is empty."""
        title = meta.title or fallback_title
        if meta.artist:
            title = f"{meta.artist} - {title}"
        self._title.setText(title)
        self._tech.setText(meta.tech_info)

        if meta.cover_art:
            pixmap = QPixmap()
            if pixmap.loadFromData(meta.cover_art):
                self._art.set_pixmap(pixmap)
                return
        self._art.set_pixmap(None)

    def set_position(self, position_ms: int, length_ms: int) -> None:
        """Update the big elapsed / total time labels."""
        elapsed = format_ms(position_ms)
        total = format_ms(length_ms)
        self._apply_fixed_width(self._elapsed, elapsed)
        self._apply_fixed_width(self._total, total)
        self._elapsed.setText(elapsed)
        self._total.setText(total)

    @staticmethod
    def _apply_fixed_width(label: QLabel, text: str) -> None:
        """Pin *label* to the pixel width of *text* with all digits widened.

        Prevents the right-aligned time labels from jittering as the digits
        change (and as the format grows from ``m:ss`` to ``h:mm:ss``).
        """
        # Use the widest common digit so every value of the same format maps
        # to an identical width.
        template = "".join("8" if ch.isdigit() else ch for ch in text)
        width = label.fontMetrics().horizontalAdvance(template)
        label.setFixedWidth(width)

    @property
    def mini_spectrum(self) -> MiniSpectrum:
        return self._mini

    @property
    def has_art(self) -> bool:
        return self._art.has_pixmap()
