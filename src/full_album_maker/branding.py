from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .paths import asset_path


def brand_pixmap(size: int = 64) -> QPixmap:
    path = asset_path("logo.svg")
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    if not path.exists():
        return pixmap

    renderer = QSvgRenderer(str(path))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pixmap


def brand_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 96, 128):
        icon.addPixmap(brand_pixmap(size))
    return icon
