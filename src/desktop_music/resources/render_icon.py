"""Render app_icon.svg to PNG (+ ICO) using Qt's own SVG renderer.

Run with:  QT_QPA_PLATFORM=offscreen uv run python -m desktop_music.resources.render_icon

Using QtSvg guarantees the raster output matches what Qt draws for the
window icon at runtime, avoiding renderer discrepancies with external tools.
"""

from __future__ import annotations

import pathlib
import struct

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication

_HERE = pathlib.Path(__file__).resolve().parent
_SVG = _HERE / "app_icon.svg"
_SIZES = (16, 32, 48, 64, 128, 256)

# Taskbar overlay badges (play/pause). Windows wants a 16x16 overlay at 96 dpi;
# we also render 32px for high-DPI taskbars.
_OVERLAY_SVGS = ("overlay_play", "overlay_pause")
_OVERLAY_SIZES = (16, 32)

# File-type icons shown by Windows Explorer for associated media files.
# Written as multi-resolution .ico so Explorer picks a crisp size.
_FILE_ICON_SVGS = ("file_audio", "file_video")
_FILE_ICON_SIZES = (16, 32, 48, 64, 128, 256)


def _render(svg_path: pathlib.Path, size: int) -> QImage:
    renderer = QSvgRenderer(str(svg_path))
    image = QImage(QSize(size, size), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    return image


def _png_bytes(image: QImage) -> bytes:
    """Encode a QImage to PNG and return the raw bytes."""
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    buf.close()
    return bytes(ba)


def _write_ico(images: list[QImage], out_path: pathlib.Path) -> None:
    """Write *images* as a single multi-resolution Windows .ico file.

    Each entry stores a PNG-compressed image (supported by Windows Vista+),
    which keeps the file small and preserves the alpha channel. Built by hand
    so no third-party imaging library is required.
    """
    entries = [(img, _png_bytes(img)) for img in images]
    count = len(entries)

    # ICONDIR header: reserved(0), type(1=icon), count.
    header = struct.pack("<HHH", 0, 1, count)

    # Directory entries are fixed 16 bytes each; image data follows.
    dir_blob = b""
    offset = 6 + 16 * count
    data_blob = b""
    for img, png in entries:
        w = img.width()
        h = img.height()
        # 0 in the width/height byte means 256.
        bw = 0 if w >= 256 else w
        bh = 0 if h >= 256 else h
        dir_blob += struct.pack(
            "<BBBBHHII",
            bw,          # width
            bh,          # height
            0,           # color count (0 = >=8bpp)
            0,           # reserved
            1,           # color planes
            32,          # bits per pixel
            len(png),    # size of image data
            offset,      # offset of image data
        )
        data_blob += png
        offset += len(png)

    out_path.write_bytes(header + dir_blob + data_blob)


def main() -> int:
    # A QApplication (even offscreen) is required for QImage/QPainter.
    app = QApplication.instance() or QApplication([])
    assert app is not None

    images: list[QImage] = []
    for size in _SIZES:
        img = _render(_SVG, size)
        out = _HERE / f"app_icon_{size}.png"
        img.save(str(out), "PNG")
        images.append(img)
        print(f"wrote {out.name}")

    # primary png = largest
    primary = _HERE / "app_icon.png"
    images[-1].save(str(primary), "PNG")
    print(f"wrote {primary.name}")

    # app_icon.ico (multi-resolution) for the Windows window/exe icon.
    app_ico = _HERE / "app_icon.ico"
    _write_ico(images, app_ico)
    print(f"wrote {app_ico.name}")

    # Overlay badges.
    for name in _OVERLAY_SVGS:
        svg = _HERE / f"{name}.svg"
        for size in _OVERLAY_SIZES:
            img = _render(svg, size)
            out = _HERE / f"{name}_{size}.png"
            img.save(str(out), "PNG")
            print(f"wrote {out.name}")

    # File-type icons (audio/video) as multi-resolution .ico for Explorer.
    for name in _FILE_ICON_SVGS:
        svg = _HERE / f"{name}.svg"
        ico_images = [_render(svg, size) for size in _FILE_ICON_SIZES]
        ico_out = _HERE / f"{name}.ico"
        _write_ico(ico_images, ico_out)
        print(f"wrote {ico_out.name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
