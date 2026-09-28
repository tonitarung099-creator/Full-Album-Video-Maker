from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import QWidget

from .editor_models import ProjectDocument, TIMEBASE
from .editor_session import TimelineScale
from .timeline_resolver import TimelineResolver


@dataclass
class _Gesture:
    layer_id: str
    mode: str
    start_x: float
    initial_start_tick: int
    initial_duration_tick: int
    pixels_per_second: float


@dataclass
class _SongGesture:
    song_id: str
    start_x: float
    initial_start_tick: int
    pixels_per_second: float


class TimelineCanvas(QWidget):
    layerSelected = Signal(object)
    songSelected = Signal(object)
    playheadRequested = Signal(int)
    moveRequested = Signal(str, int, float)
    trimRequested = Signal(str, int, float)
    songMoveRequested = Signal(str, int, float)
    trackEnabledRequested = Signal(str, bool)
    trackLockedRequested = Signal(str, bool)
    zoomStepRequested = Signal(int)

    RULER_H = 30
    LABEL_W = 132
    LANE_H = 56
    RIGHT_PAD = 80

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("editorTimelineCanvas")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._document = ProjectDocument.new_empty()
        self._resolved = TimelineResolver().resolve(self._document)
        self._pixels_per_second = 80.0
        self._playhead_tick = 0
        self._selected: set[str] = set()
        self._layer_rects: list[tuple[QRectF, str]] = []
        self._song_rects: list[tuple[QRectF, str]] = []
        self._eye_rects: list[tuple[QRectF, str]] = []
        self._lock_rects: list[tuple[QRectF, str]] = []
        self._gesture: _Gesture | None = None
        self._song_gesture: _SongGesture | None = None
        self._ghost_delta_px = 0.0
        self._update_extent()

    @property
    def pixels_per_second(self) -> float:
        return self._pixels_per_second

    def set_document(self, document: ProjectDocument) -> None:
        self._document = document.clone()
        self._resolved = TimelineResolver().resolve(self._document)
        self._selected.intersection_update(self._document.layer_map().keys())
        self._playhead_tick = min(
            self._playhead_tick,
            max(0, self._resolved.duration_tick),
        )
        self._update_extent()
        self.update()

    def set_selected_layers(self, layer_ids: list[str]) -> None:
        self._selected = set(layer_ids)
        self.update()

    def set_playhead(self, tick: int) -> None:
        self._playhead_tick = max(
            0,
            min(int(tick), max(0, self._resolved.duration_tick)),
        )
        self.update()

    def set_pixels_per_second(self, value: float) -> None:
        self._pixels_per_second = max(8.0, min(600.0, float(value)))
        self._update_extent()
        self.update()

    def _update_extent(self) -> None:
        seconds = (
            self._resolved.duration_tick / TIMEBASE
            if self._resolved.duration_tick > 0
            else 10.0
        )
        width = int(
            self.LABEL_W
            + max(600.0, seconds * self._pixels_per_second)
            + self.RIGHT_PAD
        )
        track_count = max(1, len(self._document.tracks))
        height = self.RULER_H + track_count * self.LANE_H + 10
        self.setMinimumSize(width, height)
        self.resize(max(width, self.width()), height)

    def _x_for_tick(self, tick: int, *, pps: float | None = None) -> float:
        return self.LABEL_W + TimelineScale(
            pps or self._pixels_per_second
        ).tick_to_px(tick)

    def _tick_for_x(self, x: float, *, pps: float | None = None) -> int:
        return TimelineScale(pps or self._pixels_per_second).px_to_tick(
            max(0.0, x - self.LABEL_W)
        )

    def _track_y(self, index: int) -> float:
        return self.RULER_H + index * self.LANE_H

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#07111d"))
        self._layer_rects.clear()
        self._song_rects.clear()
        self._eye_rects.clear()
        self._lock_rects.clear()

        self._paint_ruler(painter)
        tracks = sorted(self._document.tracks, key=lambda item: item.order)
        track_index = {track.track_id: i for i, track in enumerate(tracks)}

        for index, track in enumerate(tracks):
            y = self._track_y(index)
            bg = QColor("#0c1725") if index % 2 == 0 else QColor("#0a1420")
            painter.fillRect(QRectF(0, y, self.width(), self.LANE_H), bg)
            painter.setPen(QPen(QColor("#1c2c40"), 1))
            painter.drawLine(
                0,
                int(y + self.LANE_H - 1),
                self.width(),
                int(y + self.LANE_H - 1),
            )

            painter.setPen(
                QColor("#d8e5f5") if track.enabled else QColor("#64758b")
            )
            painter.drawText(
                QRectF(58, y + 5, self.LABEL_W - 62, 20),
                Qt.AlignmentFlag.AlignLeft,
                track.name[:18],
            )
            painter.setPen(QColor("#718299"))
            mode_suffix = (
                " • FREE"
                if track.kind == "audio" and self._document.playlist.mode == "free"
                else ""
            )
            painter.drawText(
                QRectF(58, y + 25, self.LABEL_W - 62, 18),
                Qt.AlignmentFlag.AlignLeft,
                track.kind.upper() + mode_suffix,
            )

            eye = QRectF(8, y + 14, 20, 20)
            lock = QRectF(32, y + 14, 20, 20)
            self._eye_rects.append((eye, track.track_id))
            self._lock_rects.append((lock, track.track_id))
            painter.setPen(
                QColor("#6fe0ff") if track.enabled else QColor("#53657a")
            )
            painter.drawText(
                eye,
                Qt.AlignmentFlag.AlignCenter,
                "●" if track.enabled else "○",
            )
            painter.setPen(
                QColor("#ffbd66") if track.locked else QColor("#8294aa")
            )
            painter.drawText(
                lock,
                Qt.AlignmentFlag.AlignCenter,
                "L" if track.locked else "U",
            )

        resolved_by_layer = {
            item.layer_id: item for item in self._resolved.layers
        }
        for layer in sorted(self._document.layers, key=lambda item: item.order):
            index = track_index.get(layer.track_id)
            if index is None:
                continue
            track = tracks[index]
            if not layer.enabled or not track.enabled:
                continue
            item = resolved_by_layer.get(layer.layer_id)
            if item is None:
                continue
            for interval in item.intervals:
                x0 = self._x_for_tick(interval.start_tick)
                x1 = self._x_for_tick(interval.end_tick)
                y = self._track_y(index) + 7
                rect = QRectF(
                    x0 + 1,
                    y,
                    max(4.0, x1 - x0 - 2),
                    self.LANE_H - 14,
                )
                if (
                    self._gesture
                    and self._gesture.layer_id == layer.layer_id
                    and self._gesture.mode == "move"
                ):
                    rect.translate(self._ghost_delta_px, 0)
                self._layer_rects.append((rect, layer.layer_id))
                self._paint_layer(painter, rect, layer, track.locked)

        audio_track_index = next(
            (i for i, track in enumerate(tracks) if track.kind == "audio"),
            None,
        )
        if audio_track_index is not None:
            audio_track = tracks[audio_track_index]
            y = self._track_y(audio_track_index) + 7
            song_map = self._document.song_map()
            for idx, song in enumerate(self._resolved.songs):
                rect = QRectF(
                    self._x_for_tick(song.start_tick) + 1,
                    y,
                    max(
                        4.0,
                        self._x_for_tick(song.end_tick)
                        - self._x_for_tick(song.start_tick)
                        - 2,
                    ),
                    self.LANE_H - 14,
                )
                if (
                    self._song_gesture
                    and self._song_gesture.song_id == song.song_id
                ):
                    rect.translate(self._ghost_delta_px, 0)
                self._song_rects.append((rect, song.song_id))
                item = song_map.get(song.song_id)
                has_fade = bool(item and item.crossfade_in_tick > 0)
                color = QColor("#245f8f" if idx % 2 == 0 else "#3b4f99")
                if self._document.playlist.mode == "free":
                    color = QColor("#1f6f75" if idx % 2 == 0 else "#315f83")
                if audio_track.locked:
                    color = color.darker(145)
                painter.setBrush(color)
                painter.setPen(QPen(QColor("#65dcff"), 1))
                painter.drawRoundedRect(rect, 4, 4)
                painter.setPen(QColor("#e9f2ff"))
                title = (item.display_title if item else "") or f"Song {idx + 1:02d}"
                suffix = "  ↔" if has_fade else ""
                painter.drawText(
                    rect.adjusted(6, 0, -4, 0),
                    Qt.AlignmentFlag.AlignVCenter,
                    title[:28] + suffix,
                )

        playhead_x = self._x_for_tick(self._playhead_tick)
        painter.setPen(QPen(QColor("#ff496f"), 2))
        painter.drawLine(
            int(playhead_x),
            0,
            int(playhead_x),
            self.height(),
        )
        painter.setBrush(QColor("#ff496f"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(
            [
                QPointF(playhead_x - 6, 0),
                QPointF(playhead_x + 6, 0),
                QPointF(playhead_x, 8),
            ]
        )
        painter.end()

    def _paint_ruler(self, painter: QPainter) -> None:
        painter.fillRect(
            QRectF(0, 0, self.width(), self.RULER_H),
            QColor("#091522"),
        )
        painter.setPen(QPen(QColor("#27384c"), 1))
        painter.drawLine(
            self.LABEL_W,
            self.RULER_H - 1,
            self.width(),
            self.RULER_H - 1,
        )
        visible_seconds = max(
            1.0,
            (self.width() - self.LABEL_W) / self._pixels_per_second,
        )
        if self._pixels_per_second >= 180:
            step = 1
        elif self._pixels_per_second >= 70:
            step = 5
        elif self._pixels_per_second >= 25:
            step = 15
        else:
            step = 60
        total_seconds = int(
            max(visible_seconds, self._resolved.duration_tick / TIMEBASE)
        ) + step
        for seconds in range(0, total_seconds + 1, step):
            x = self.LABEL_W + seconds * self._pixels_per_second
            painter.setPen(QColor("#72849a"))
            painter.drawLine(int(x), 18, int(x), self.RULER_H - 1)
            minutes, sec = divmod(seconds, 60)
            hours, minutes = divmod(minutes, 60)
            text = (
                f"{hours:02d}:{minutes:02d}:{sec:02d}"
                if hours
                else f"{minutes:02d}:{sec:02d}"
            )
            painter.drawText(
                QRectF(x + 3, 1, 72, 16),
                Qt.AlignmentFlag.AlignLeft,
                text,
            )

    def _paint_layer(
        self,
        painter: QPainter,
        rect: QRectF,
        layer,
        track_locked: bool,
    ) -> None:
        colors = {
            "background": QColor("#1c8a6d"),
            "text": QColor("#8b55d7"),
            "song_title": QColor("#995aaf"),
            "spectrum": QColor("#c27032"),
        }
        color = colors.get(layer.type, QColor("#376b9d"))
        if layer.locked or track_locked:
            color = color.darker(145)
        painter.setBrush(color)
        selected = layer.layer_id in self._selected
        painter.setPen(
            QPen(
                QColor("#ffffff") if selected else color.lighter(145),
                2 if selected else 1,
            )
        )
        painter.drawRoundedRect(rect, 4, 4)
        painter.setPen(QColor("#ffffff"))
        suffix = "  🔒" if layer.locked or track_locked else ""
        painter.drawText(
            rect.adjusted(6, 0, -10, 0),
            Qt.AlignmentFlag.AlignVCenter,
            (layer.name or layer.type)[:28] + suffix,
        )
        if selected and rect.width() >= 14:
            painter.setBrush(QColor("#ffffff"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(
                QRectF(
                    rect.right() - 4,
                    rect.top() + 5,
                    3,
                    max(4, rect.height() - 10),
                )
            )

    @staticmethod
    def _contains(
        entries: list[tuple[QRectF, str]],
        pos: QPointF,
    ) -> str | None:
        for rect, item_id in reversed(entries):
            if rect.contains(pos):
                return item_id
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        pos = event.position()
        track_id = self._contains(self._eye_rects, pos)
        if track_id:
            track = next(
                item for item in self._document.tracks if item.track_id == track_id
            )
            self.trackEnabledRequested.emit(track_id, not track.enabled)
            event.accept()
            return
        track_id = self._contains(self._lock_rects, pos)
        if track_id:
            track = next(
                item for item in self._document.tracks if item.track_id == track_id
            )
            self.trackLockedRequested.emit(track_id, not track.locked)
            event.accept()
            return
        if pos.y() <= self.RULER_H:
            self.playheadRequested.emit(self._tick_for_x(pos.x()))
            event.accept()
            return

        song_id = self._contains(self._song_rects, pos)
        if song_id is not None:
            self.songSelected.emit(song_id)
            if self._document.playlist.mode != "free":
                event.accept()
                return
            audio_track = next(
                (track for track in self._document.tracks if track.kind == "audio"),
                None,
            )
            if audio_track is None or audio_track.locked or not audio_track.enabled:
                event.accept()
                return
            resolved_song = next(
                (item for item in self._resolved.songs if item.song_id == song_id),
                None,
            )
            if resolved_song is None:
                event.accept()
                return
            self._song_gesture = _SongGesture(
                song_id=song_id,
                start_x=pos.x(),
                initial_start_tick=resolved_song.start_tick,
                pixels_per_second=self._pixels_per_second,
            )
            self._ghost_delta_px = 0.0
            self.grabMouse()
            event.accept()
            return

        layer_id = self._contains(self._layer_rects, pos)
        if layer_id is None:
            self.layerSelected.emit(None)
            return
        self.layerSelected.emit(layer_id)
        layer = self._document.layer_map()[layer_id]
        track = next(
            item for item in self._document.tracks if item.track_id == layer.track_id
        )
        if layer.locked or track.locked:
            return
        rect = next(
            rect
            for rect, value in reversed(self._layer_rects)
            if value == layer_id and rect.contains(pos)
        )
        mode = "trim" if abs(rect.right() - pos.x()) <= 9 else "move"
        resolved_item = next(
            (
                item
                for item in self._resolved.layers
                if item.layer_id == layer_id
            ),
            None,
        )
        if resolved_item is None or not resolved_item.intervals:
            return
        first = min(
            resolved_item.intervals,
            key=lambda item: item.start_tick,
        )
        duration = layer.time_binding.duration_tick or (
            first.end_tick - first.start_tick
        )
        self._gesture = _Gesture(
            layer_id=layer_id,
            mode=mode,
            start_x=pos.x(),
            initial_start_tick=first.start_tick,
            initial_duration_tick=max(1, duration),
            pixels_per_second=self._pixels_per_second,
        )
        self._ghost_delta_px = 0.0
        self.grabMouse()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._song_gesture is not None:
            self._ghost_delta_px = event.position().x() - self._song_gesture.start_x
            self.update()
            event.accept()
            return
        if self._gesture is None:
            return super().mouseMoveEvent(event)
        self._ghost_delta_px = event.position().x() - self._gesture.start_x
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mouseReleaseEvent(event)
        if self._song_gesture is not None:
            gesture = self._song_gesture
            delta_px = event.position().x() - gesture.start_x
            delta_tick = TimelineScale(
                gesture.pixels_per_second
            ).delta_px_to_tick(delta_px)
            self._song_gesture = None
            self._ghost_delta_px = 0.0
            self.releaseMouse()
            target = max(0, gesture.initial_start_tick + delta_tick)
            self.songMoveRequested.emit(
                gesture.song_id,
                target,
                gesture.pixels_per_second,
            )
            self.update()
            event.accept()
            return
        if self._gesture is None:
            return super().mouseReleaseEvent(event)
        gesture = self._gesture
        delta_px = event.position().x() - gesture.start_x
        delta_tick = TimelineScale(
            gesture.pixels_per_second
        ).delta_px_to_tick(delta_px)
        self._gesture = None
        self._ghost_delta_px = 0.0
        self.releaseMouse()
        if gesture.mode == "move":
            target = max(0, gesture.initial_start_tick + delta_tick)
            self.moveRequested.emit(
                gesture.layer_id,
                target,
                gesture.pixels_per_second,
            )
        else:
            duration = max(1, gesture.initial_duration_tick + delta_tick)
            self.trimRequested.emit(
                gesture.layer_id,
                duration,
                gesture.pixels_per_second,
            )
        self.update()
        event.accept()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoomStepRequested.emit(
                1 if event.angleDelta().y() > 0 else -1
            )
            event.accept()
            return
        super().wheelEvent(event)