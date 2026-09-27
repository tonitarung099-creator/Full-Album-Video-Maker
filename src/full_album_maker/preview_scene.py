from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .editor_models import ProjectDocument, Transform
from .timeline_resolver import TimelineResolver


@dataclass
class _TransformGesture:
    layer_id: str
    mode: str
    start_pos: QPointF
    start_transform: Transform
    canvas_rect: QRectF
    start_angle: float = 0.0


class PreviewCanvas(QWidget):
    transformCommitted = Signal(str, object)
    layerSelected = Signal(object)

    HANDLE = 9.0

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("editorPreviewCanvas")
        self.setMinimumSize(360, 210)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._document = ProjectDocument.new_empty()
        self._playhead_tick = 0
        self._selected_layer_id: str | None = None
        self._gesture: _TransformGesture | None = None
        self._preview_transform: Transform | None = None
        self._accurate_frame = QImage()
        self._accurate_frame_path = ""

    def set_document(self, document: ProjectDocument) -> None:
        self._document = document.clone()
        if self._selected_layer_id not in self._document.layer_map():
            self._selected_layer_id = None
        self.update()

    def set_playhead(self, tick: int) -> None:
        self._playhead_tick = max(0, int(tick))
        self.update()

    def set_selected_layer(self, layer_id: str | None) -> None:
        self._selected_layer_id = layer_id if layer_id in self._document.layer_map() else None
        self._preview_transform = None
        self.update()

    def set_accurate_frame(self, path: str | Path | None) -> None:
        value = str(path or "")
        image = QImage(value) if value else QImage()
        self._accurate_frame = image if not image.isNull() else QImage()
        self._accurate_frame_path = value if not self._accurate_frame.isNull() else ""
        self.update()

    def clear_accurate_frame(self) -> None:
        self._accurate_frame = QImage()
        self._accurate_frame_path = ""
        self.update()

    def _canvas_rect(self) -> QRectF:
        margin = 12.0
        available_w = max(1.0, self.width() - margin * 2)
        available_h = max(1.0, self.height() - margin * 2)
        aspect = self._document.canvas.width / max(1, self._document.canvas.height)
        width = min(available_w, available_h * aspect)
        height = width / aspect
        if height > available_h:
            height = available_h
            width = height * aspect
        left = (self.width() - width) / 2
        top = (self.height() - height) / 2
        return QRectF(left, top, width, height)

    @staticmethod
    def _rect_for_transform(canvas: QRectF, transform: Transform) -> QRectF:
        return QRectF(
            canvas.left() + transform.x * canvas.width(),
            canvas.top() + transform.y * canvas.height(),
            transform.width * canvas.width(),
            transform.height * canvas.height(),
        )

    @staticmethod
    def _supports_box_transform(layer) -> bool:
        return layer.type == "background"

    def _current_transform(self, layer_id: str) -> Transform:
        if layer_id == self._selected_layer_id and self._preview_transform is not None:
            return self._preview_transform
        return self._document.layer_map()[layer_id].transform

    def _active_layer_ids(self) -> set[str]:
        resolved = TimelineResolver().resolve(self._document)
        active: set[str] = set()
        for item in resolved.layers:
            for interval in item.intervals:
                if interval.start_tick <= self._playhead_tick < interval.end_tick:
                    active.add(item.layer_id)
                    break
        return active

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#050b12"))
        canvas = self._canvas_rect()
        painter.setPen(QPen(QColor("#25384c"), 1))
        painter.setBrush(QColor(self._document.canvas.background_color))
        painter.drawRect(canvas)

        if not self._accurate_frame.isNull():
            painter.drawImage(canvas, self._accurate_frame)

        active = self._active_layer_ids()
        tracks = {track.track_id: track for track in self._document.tracks}
        for layer in sorted(self._document.layers, key=lambda item: item.order):
            track = tracks.get(layer.track_id)
            if layer.layer_id not in active or not layer.enabled or track is None or not track.enabled:
                continue
            transform = self._current_transform(layer.layer_id)
            rect = self._rect_for_transform(canvas, transform)
            painter.save()
            if self._supports_box_transform(layer):
                center = rect.center()
                painter.translate(center)
                painter.rotate(transform.rotation)
                painter.translate(-center)
            if self._accurate_frame.isNull():
                self._paint_approx_layer(painter, rect, layer)
            if layer.layer_id == self._selected_layer_id:
                self._paint_selection(painter, rect, layer, track.locked)
            painter.restore()

        if self._selected_layer_id and self._selected_layer_id not in active:
            painter.setPen(QColor("#73869b"))
            painter.drawText(
                canvas.adjusted(8, 8, -8, -8),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
                "Layer terpilih tidak aktif di playhead ini",
            )
        painter.end()

    def _paint_approx_layer(self, painter: QPainter, rect: QRectF, layer) -> None:
        if layer.type == "background":
            mode = str(layer.properties.get("mode", "asset" if layer.asset_refs else "solid"))
            if mode == "solid":
                painter.fillRect(rect, QColor(str(layer.properties.get("color", "#202b3b"))))
            else:
                painter.setPen(QPen(QColor("#4cc2ff"), 1))
                painter.setBrush(QColor(22, 74, 99, 170))
                painter.drawRect(rect)
                painter.setPen(QColor("#bfeeff"))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "VISUAL")
            return
        if layer.type in {"text", "song_title"}:
            painter.setPen(QColor(str(layer.properties.get("color", "#ffffff"))))
            text = str(layer.properties.get("text", layer.name or "Teks"))
            painter.drawText(
                rect.adjusted(5, 4, -5, -4),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                text,
            )
            return
        painter.setPen(QPen(QColor("#9db4ce"), 1, Qt.PenStyle.DashLine))
        painter.drawRect(rect)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, layer.type.upper())

    def _paint_selection(self, painter: QPainter, rect: QRectF, layer, track_locked: bool) -> None:
        locked = layer.locked or track_locked
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#ffce5c") if locked else QColor("#5ee6ff"), 2))
        painter.drawRect(rect)
        if locked or not self._supports_box_transform(layer):
            return
        painter.setBrush(QColor("#5ee6ff"))
        painter.setPen(Qt.PenStyle.NoPen)
        for point in (rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight()):
            painter.drawRect(QRectF(point.x() - 4, point.y() - 4, 8, 8))
        handle = QPointF(rect.center().x(), rect.top() - 18)
        painter.setPen(QPen(QColor("#5ee6ff"), 1))
        painter.drawLine(rect.center().x(), rect.top(), handle.x(), handle.y())
        painter.setBrush(QColor("#5ee6ff"))
        painter.drawEllipse(handle, 5, 5)

    def _selected_geometry(self) -> tuple[object, object, QRectF, QPointF] | None:
        if not self._selected_layer_id:
            return None
        layer = self._document.layer_map().get(self._selected_layer_id)
        if layer is None:
            return None
        track = next((item for item in self._document.tracks if item.track_id == layer.track_id), None)
        if track is None:
            return None
        transform = self._current_transform(layer.layer_id)
        rect = self._rect_for_transform(self._canvas_rect(), transform)
        rotation_handle = QPointF(rect.center().x(), rect.top() - 18)
        return layer, track, rect, rotation_handle

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        pos = event.position()
        geometry = self._selected_geometry()
        if geometry:
            layer, track, rect, rotation_handle = geometry
            if not layer.locked and not track.locked:
                mode = ""
                if self._supports_box_transform(layer):
                    if math.hypot(pos.x() - rotation_handle.x(), pos.y() - rotation_handle.y()) <= 10:
                        mode = "rotate"
                    elif math.hypot(pos.x() - rect.right(), pos.y() - rect.bottom()) <= 13:
                        mode = "resize"
                if not mode and rect.adjusted(-3, -3, 3, 3).contains(pos):
                    mode = "move"
                if mode:
                    center = rect.center()
                    angle = math.degrees(math.atan2(pos.y() - center.y(), pos.x() - center.x()))
                    self._gesture = _TransformGesture(
                        layer.layer_id,
                        mode,
                        QPointF(pos),
                        Transform(**vars(layer.transform)),
                        self._canvas_rect(),
                        angle,
                    )
                    self._preview_transform = Transform(**vars(layer.transform))
                    self.grabMouse()
                    event.accept()
                    return

        active = self._active_layer_ids()
        canvas = self._canvas_rect()
        tracks = {track.track_id: track for track in self._document.tracks}
        for layer in sorted(self._document.layers, key=lambda item: item.order, reverse=True):
            if layer.layer_id not in active or not layer.enabled:
                continue
            track = tracks.get(layer.track_id)
            if track is None or not track.enabled:
                continue
            rect = self._rect_for_transform(canvas, layer.transform)
            if rect.contains(pos):
                self.layerSelected.emit(layer.layer_id)
                event.accept()
                return
        self.layerSelected.emit(None)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._gesture is None or self._preview_transform is None:
            return super().mouseMoveEvent(event)
        gesture = self._gesture
        pos = event.position()
        transform = Transform(**vars(gesture.start_transform))
        canvas = gesture.canvas_rect
        if gesture.mode == "move":
            transform.x += (pos.x() - gesture.start_pos.x()) / max(1.0, canvas.width())
            transform.y += (pos.y() - gesture.start_pos.y()) / max(1.0, canvas.height())
            transform.x = max(-2.0, min(2.0, transform.x))
            transform.y = max(-2.0, min(2.0, transform.y))
        elif gesture.mode == "resize":
            transform.width += (pos.x() - gesture.start_pos.x()) / max(1.0, canvas.width())
            transform.height += (pos.y() - gesture.start_pos.y()) / max(1.0, canvas.height())
            transform.width = max(0.02, min(3.0, transform.width))
            transform.height = max(0.02, min(3.0, transform.height))
        else:
            rect = self._rect_for_transform(canvas, gesture.start_transform)
            center = rect.center()
            angle = math.degrees(math.atan2(pos.y() - center.y(), pos.x() - center.x()))
            transform.rotation = gesture.start_transform.rotation + (angle - gesture.start_angle)
            while transform.rotation > 180:
                transform.rotation -= 360
            while transform.rotation < -180:
                transform.rotation += 360
        self._preview_transform = transform
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._gesture is None:
            return super().mouseReleaseEvent(event)
        gesture = self._gesture
        transform = self._preview_transform
        self._gesture = None
        self._preview_transform = None
        self.releaseMouse()
        if transform is not None:
            self.transformCommitted.emit(gesture.layer_id, transform)
        self.update()
        event.accept()
