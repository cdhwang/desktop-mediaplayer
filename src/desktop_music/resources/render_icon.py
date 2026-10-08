"""Render app_icon.svg to PNG (+ ICO) using Qt's own SVG renderer.

Run with:  QT_QPA_PLATFORM=offscreen uv run python -m desktop_music.resources.render_icon

Using QtSvg guarantees the raster output matches what Qt draws for the
window icon at runtime, avoiding renderer discrepancies with external tools.
"""

from __future__ import annotations

import pathlib

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication

_HERE = pathlib.Path(__file__).resolve().parent
_SVG = _HERE / "app_icon.svg"
_SIZES = (16, 32, 48, 64, 128, 256)


def _render(size: int) -> QImage:
    renderer = QSvgRenderer(str(_SVG))
    image = QImage(QSize(size, size), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    return image


def main() -> int:
    # A QApplication (even offscreen) is required for QImage/QPainter.
    app = QApplication.instance() or QApplication([])
    assert app is not None

    images: list[QImage] = []
    for size in _SIZES:
        img = _render(size)
        out = _HERE / f"app_icon_{size}.png"
        img.save(str(out), "PNG")
        images.append(img)
        print(f"wrote {out.name}")

    # primary png = largest
    primary = _HERE / "app_icon.png"
    images[-1].save(str(primary), "PNG")
    print(f"wrote {primary.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
