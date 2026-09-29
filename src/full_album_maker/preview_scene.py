from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .album_visuals import format_duration_tick, normalize_visual_properties
from .editor_models import ProjectDocument, Transform
from .spectrum_feature import dynamic_song_text, normalize_spectrum_properties
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
        return layer.type in {
            "background",
            "spectrum",
            "song_cover",
            "vinyl",
            "playlist_visual",
            "progress",
        }

    def _current_transform(self, layer_id: str) -> Transform:
        if layer_id == self._selected_layer_id and self._preview_transform is not None:
            return self._preview_transform
        return self._document.layer_map()[layer_id].transform

    def _resolved(self):
        return TimelineResolver().resolve(self._document)

    def _active_layer_ids(self) -> set[str]:
        resolved = self._resolved()
        active: set[str] = set()
        for item in resolved.layers:
            for interval in item.intervals:
                if interval.start_tick <= self._playhead_tick < interval.end_tick:
                    active.add(item.layer_id)
                    break
        return active

    def _active_song_event(self):
        for event in self._resolved().songs:
            if event.start_tick <= self._playhead_tick < event.end_tick:
                return event
        return None

    def _active_song(self):
        event = self._active_song_event()
        return self._document.song_map().get(event.song_id) if event is not None else None

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
                motion = str(layer.properties.get("motion", "static"))
                playback = str(layer.properties.get("playback", "loop"))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"VISUAL\n{motion} / {playback}")
            return

        if layer.type == "song_cover":
            props = normalize_visual_properties("song_cover", layer.properties)
            song = self._active_song()
            asset_id = (song.cover_asset_id if song and song.cover_asset_id else None) or props["fallback_asset_id"]
            asset = self._document.asset_map().get(asset_id) if asset_id else None
            image = QImage(asset.locator) if asset is not None else QImage()
            if not image.isNull():
                scaled = image.scaled(
                    max(1, int(rect.width())),
                    max(1, int(rect.height())),
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding if props["fit"] == "fill" else Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                source = QRectF(
                    max(0.0, (scaled.width() - rect.width()) / 2),
                    max(0.0, (scaled.height() - rect.height()) / 2),
                    min(rect.width(), scaled.width()),
                    min(rect.height(), scaled.height()),
                )
                target = QRectF(rect.left(), rect.top(), source.width(), source.height())
                painter.drawImage(target, scaled, source)
            else:
                painter.fillRect(rect, QColor("#20252c"))
                painter.setPen(QColor("#9ba8b5"))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "COVER\nBELUM ADA")
            return

        if layer.type == "vinyl":
            props = normalize_visual_properties("vinyl", layer.properties)
            size = min(rect.width(), rect.height())
            disc = QRectF(rect.center().x() - size / 2, rect.center().y() - size / 2, size, size)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(props["color"]))
            painter.drawEllipse(disc)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(props["groove_color"]), max(1.0, size * 0.008)))
            for ratio in (0.82, 0.67, 0.52, 0.38):
                margin = size * (1 - ratio) / 2
                painter.drawEllipse(disc.adjusted(margin, margin, -margin, -margin))
            center_size = size * props["center_ratio"] * 2
            center = QRectF(
                disc.center().x() - center_size / 2,
                disc.center().y() - center_size / 2,
                center_size,
                center_size,
            )
            painter.setBrush(QColor(props["center_color"]))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(center)
            angle = (self._playhead_tick / 240000.0) / props["spin_seconds"] * math.tau
            edge = QPointF(
                disc.center().x() + math.cos(angle) * size * 0.42,
                disc.center().y() + math.sin(angle) * size * 0.42,
            )
            painter.setPen(QPen(QColor("#737373"), max(1.0, size * 0.01)))
            painter.drawLine(disc.center(), edge)
            return

        if layer.type == "playlist_visual":
            props = normalize_visual_properties("playlist_visual", layer.properties)
            bg = QColor("#000000")
            bg.setAlphaF(props["background_opacity"])
            painter.fillRect(rect, bg)
            active = self._active_song()
            songs = [song for song in self._document.playlist.entries if song.enabled][: props["max_items"]]
            if not songs:
                painter.setPen(QColor(props["color"]))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "PLAYLIST KOSONG")
                return
            row_h = rect.height() / max(1, len(songs))
            for index, song in enumerate(songs):
                color = props["active_color"] if active and active.song_id == song.song_id else props["color"]
                painter.setPen(QColor(color))
                title = song.display_title or Path(self._document.asset_map()[song.asset_id].locator).stem
                artist = f" — {song.display_artist}" if props["show_artist"] and song.display_artist else ""
                number = f"{index + 1:02d}. " if props["numbered"] else ""
                row = QRectF(rect.left() + 8, rect.top() + index * row_h, rect.width() - 16, row_h)
                painter.drawText(row, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"{number}{title}{artist}")
            return

        if layer.type == "progress":
            props = normalize_visual_properties("progress", layer.properties)
            resolved = self._resolved()
            ratio = 0.0
            if props["mode"] == "album":
                ratio = self._playhead_tick / max(1, resolved.duration_tick)
            else:
                event = self._active_song_event()
                if event is not None:
                    ratio = (self._playhead_tick - event.start_tick) / max(1, event.end_tick - event.start_tick)
            ratio = max(0.0, min(1.0, ratio))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(props["background_color"]))
            painter.drawRect(rect)
            painter.setBrush(QColor(props["fill_color"]))
            painter.drawRect(QRectF(rect.left(), rect.top(), rect.width() * ratio, rect.height()))
            return

        if layer.type == "song_time":
            props = normalize_visual_properties("song_time", layer.properties)
            resolved = self._resolved()
            if props["mode"] == "album":
                elapsed = min(self._playhead_tick, resolved.duration_tick)
                total = resolved.duration_tick
            else:
                event = self._active_song_event()
                if event is None:
                    elapsed = total = 0
                else:
                    elapsed = max(0, self._playhead_tick - event.start_tick)
                    total = max(0, event.end_tick - event.start_tick)
            painter.setPen(QColor(props["color"]))
            painter.drawText(
                rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"{format_duration_tick(elapsed)} / {format_duration_tick(total)}",
            )
            return

        if layer.type == "spectrum":
            try:
                props = normalize_spectrum_properties(layer.properties)
            except Exception:
                props = {"style": "bars", "color": "#4de8ff", "mirror": False, "inner_ratio": 0.58}
            color = QColor(str(props.get("color", "#4de8ff")))
            color.setAlphaF(max(0.0, min(1.0, float(layer.opacity))))
            painter.setPen(QPen(color, 2))
            style = str(props.get("style", "bars"))
            phase = (self._playhead_tick / 240000.0) * 2.7
            if style == "circular_spectrum":
                size = min(rect.width(), rect.height())
                center = rect.center()
                outer_radius = size * 0.48
                inner_radius = outer_radius * float(props.get("inner_ratio", 0.58))
                band = max(1.0, outer_radius - inner_radius)
                count = 72
                for i in range(count):
                    ratio = i / count
                    angle = ratio * math.tau - math.pi / 2
                    envelope = 0.08 + 0.88 * abs(
                        math.sin(phase + i * 0.37)
                        * math.cos(i * 0.13 + phase * 0.45)
                    )
                    end_radius = inner_radius + band * envelope
                    start = QPointF(
                        center.x() + math.cos(angle) * inner_radius,
                        center.y() + math.sin(angle) * inner_radius,
                    )
                    end = QPointF(
                        center.x() + math.cos(angle) * end_radius,
                        center.y() + math.sin(angle) * end_radius,
                    )
                    painter.drawLine(start, end)
            elif style in {"bars", "spectrum_line"}:
                count = 32
                points: list[QPointF] = []
                for i in range(count):
                    x = rect.left() + (i + 0.5) * rect.width() / count
                    envelope = 0.18 + 0.72 * abs(math.sin(phase + i * 0.47) * math.cos(i * 0.19 + phase * 0.4))
                    top = rect.bottom() - envelope * rect.height()
                    if style == "bars":
                        painter.drawLine(QPointF(x, rect.bottom()), QPointF(x, top))
                    else:
                        points.append(QPointF(x, top))
                if style == "spectrum_line" and len(points) > 1:
                    for a, b in zip(points, points[1:]):
                        painter.drawLine(a, b)
            else:
                middle = rect.center().y()
                points: list[QPointF] = []
                for i in range(64):
                    ratio = i / 63.0
                    x = rect.left() + ratio * rect.width()
                    amp = math.sin(phase * 2.0 + ratio * 18.0) * math.sin(ratio * math.pi)
                    y = middle - amp * rect.height() * 0.35
                    points.append(QPointF(x, y))
                for a, b in zip(points, points[1:]):
                    painter.drawLine(a, b)
                if style == "stereo_waveform":
                    for a, b in zip(points, points[1:]):
                        painter.drawLine(QPointF(a.x(), 2 * middle - a.y()), QPointF(b.x(), 2 * middle - b.y()))
            return

        if layer.type == "song_title":
            painter.setPen(QColor(str(layer.properties.get("color", "#ffffff"))))
            song = self._active_song()
            if song is None:
                text = "Judul Lagu\nArtis"
            else:
                text = dynamic_song_text(
                    str(layer.properties.get("template", "{title}\n{artist}")),
                    song.display_title,
                    song.display_artist,
                )
            painter.drawText(
                rect.adjusted(5, 4, -5, -4),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap,
                text,
            )
            return

        if layer.type == "text":
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
