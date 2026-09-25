from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QRectF
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "assets" / "logo.svg"
PNG = ROOT / "assets" / "logo.png"
ICO = ROOT / "assets" / "logo.ico"


def render_png(size: int = 256) -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(0)
    renderer = QSvgRenderer(str(SVG))
    if not renderer.isValid():
        raise RuntimeError("Logo SVG tidak valid.")
    painter = QPainter(image)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    if not image.save(str(PNG), "PNG"):
        raise RuntimeError("Gagal membuat logo PNG.")


def render_ico() -> None:
    source = Image.open(PNG).convert("RGBA")
    source.save(
        ICO,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


if __name__ == "__main__":
    render_png()
    render_ico()
    print(f"Logo siap: {PNG} dan {ICO}")
