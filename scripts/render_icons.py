"""Render assets/icons/polyget-<size>.png from the SVG sources.

    python scripts/render_icons.py

16 to 32 px come from polyget-small.svg (three thicker lanes, bigger head); the rest from polyget.svg.
Uses Qt's SVG renderer, which is already a dependency, so no Inkscape/rsvg is needed.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ICONS = Path(__file__).resolve().parent.parent / "assets" / "icons"
SIZES = (16, 22, 24, 32, 48, 64, 128, 256, 512)
SMALL = {16, 22, 24, 32}


def render(svg: Path, size: int, out: Path) -> None:
    renderer = QSvgRenderer(str(svg))
    if not renderer.isValid():
        raise SystemExit(f"cannot read {svg}")
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    if not image.save(str(out)):
        raise SystemExit(f"cannot write {out}")


def main() -> int:
    app = QGuiApplication(sys.argv)  # noqa: F841 - QImage/QPainter need one
    for size in SIZES:
        source = ICONS / ("polyget-small.svg" if size in SMALL else "polyget.svg")
        out = ICONS / f"polyget-{size}.png"
        render(source, size, out)
        print(f"{out.relative_to(ICONS.parent.parent)}  <- {source.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
