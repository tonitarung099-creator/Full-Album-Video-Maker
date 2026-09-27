from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .auto_arrange import AutoArrange, AutoArrangeRecipe
from .editor_commands import SetPlaylistEntries
from .editor_models import ProjectDocument, TIMEBASE
from .editor_session import EditorSession
from .paths import output_dir, temp_dir
from .playlist_commands import MoveSong, RemoveSong
from .playlist_editor import PlaylistPanel
from .playlist_service_v2 import PlaylistServiceV2
from .preview_scene import PreviewCanvas
from .preview_service import AccuratePreviewService
from .project_repository import load_project_document, save_project_document
from .property_inspector import PropertyInspector
from .render_service_v2 import EditorRenderService
from .timeline_editor import TimelineCanvas


class _AsyncBridge(QObject):
    previewReady = Signal(str)
    renderDone = Signal(str)
    error = Signal(str)
    log = Signal(str)


class EditorWorkspace(QWidget):
    documentChanged = Signal(object)
    dirtyChanged = Signal(bool)
    statusMessage = Signal(str)

    def __init__(self, document: ProjectDocument | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("editorWorkspaceV2")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.session = EditorSession(document or ProjectDocument.new_empty())
        self.current_project_path = ""
        self._last_dirty = self.session.is_dirty
        self._render_busy = False
        self._preview_busy = False

        self.bridge = _AsyncBridge(self)
        self.bridge.previewReady.connect(self._preview_ready)
        self.bridge.renderDone.connect(self._render_done)
        self.bridge.error.connect(self._async_error)
        self.bridge.log.connect(self._set_status)

        root = QVBoxLayout(self)
        root.setContentsMargins(7, 7, 7, 7)
        root.setSpacing(6)
        root.addLayout(self._toolbar())

        self.preview = PreviewCanvas(self)
        self.playlist = PlaylistPanel(self)
        self.tabs = QTabWidget(self)
        self.tabs.addTab(self.preview, "Preview")
        self.tabs.addTab(self.playlist, "Playlist")

        self.inspector = PropertyInspector(self)
        upper = QSplitter(Qt.Orientation.Horizontal, self)
        upper.setChildrenCollapsible(False)
        upper.addWidget(self.tabs)
        upper.addWidget(self.inspector)
        upper.setSizes([560, 230])
        upper.setStretchFactor(0, 1)
        upper.setStretchFactor(1, 0)

        self.timeline = TimelineCanvas(self)
        self.timeline_scroll = QScrollArea(self)
        self.timeline_scroll.setWidgetResizable(False)
        self.timeline_scroll.setWidget(self.timeline)
        self.timeline_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.timeline_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.timeline_scroll.setMinimumHeight(220)

        body = QSplitter(Qt.Orientation.Vertical, self)
        body.setChildrenCollapsible(False)
        body.addWidget(upper)
        body.addWidget(self.timeline_scroll)
        body.setSizes([360, 260])
        root.addWidget(body, 1)

        status_row = QHBoxLayout()
        self.status = QLabel("Editor v2 siap")
        self.status.setObjectName("muted")
        self.playhead_label = QLabel("00:00:00.000")
        status_row.addWidget(self.status, 1)
        status_row.addWidget(self.playhead_label)
        root.addLayout(status_row)

        self.play_timer = QTimer(self)
        self.play_timer.setInterval(33)
        self.play_timer.timeout.connect(self._playback_tick)

        self._connect_signals()
        self._refresh_all()

    def _toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(4)
        self.open_btn = QPushButton("Buka V2")
        self.save_btn = QPushButton("Simpan V2")
        self.undo_btn = QPushButton("↶")
        self.redo_btn = QPushButton("↷")
        self.add_text_btn = QPushButton("+ Teks")
        self.duplicate_btn = QPushButton("Duplikat")
        self.delete_btn = QPushButton("Hapus")
        self.use_all_btn = QPushButton("Pakai Semua Lagu")
        self.auto_btn = QPushButton("AUTO SUSUN")
        self.preview_btn = QPushButton("Preview Akurat")
        self.render_btn = QPushButton("Render V2")
        self.play_btn = QPushButton("▶")
        self.snap_check = QCheckBox("Snap")
        self.snap_check.setChecked(True)
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(8, 300)
        self.zoom_slider.setValue(80)
        self.zoom_slider.setMaximumWidth(125)

        for widget in (
            self.open_btn,
            self.save_btn,
            self.undo_btn,
            self.redo_btn,
            self.add_text_btn,
            self.duplicate_btn,
            self.delete_btn,
            self.use_all_btn,
            self.auto_btn,
            self.play_btn,
            self.preview_btn,
            self.render_btn,
        ):
            row.addWidget(widget)
        row.addWidget(self.snap_check)
        row.addWidget(QLabel("Zoom"))
        row.addWidget(self.zoom_slider)
        return row

    def _connect_signals(self) -> None:
        self.open_btn.clicked.connect(self.open_project)
        self.save_btn.clicked.connect(self.save_project)
        self.undo_btn.clicked.connect(self.undo)
        self.redo_btn.clicked.connect(self.redo)
        self.add_text_btn.clicked.connect(self.add_text)
        self.duplicate_btn.clicked.connect(self.duplicate_selected)
        self.delete_btn.clicked.connect(self.delete_selected)
        self.use_all_btn.clicked.connect(self.use_all_audio)
        self.auto_btn.clicked.connect(self.auto_arrange)
        self.preview_btn.clicked.connect(self.render_accurate_preview)
        self.render_btn.clicked.connect(self.render_project)
        self.play_btn.clicked.connect(self.toggle_playback)
        self.snap_check.toggled.connect(self._snap_changed)
        self.zoom_slider.valueChanged.connect(self._zoom_changed)

        self.timeline.layerSelected.connect(self._select_layer)
        self.timeline.playheadRequested.connect(self.set_playhead)
        self.timeline.moveRequested.connect(self._move_layer)
        self.timeline.trimRequested.connect(self._trim_layer)
        self.timeline.trackEnabledRequested.connect(self._set_track_enabled)
        self.timeline.trackLockedRequested.connect(self._set_track_locked)
        self.timeline.zoomStepRequested.connect(self._zoom_step)

        self.preview.layerSelected.connect(self._select_layer)
        self.preview.transformCommitted.connect(self._set_transform)

        self.inspector.transformEdited.connect(self._set_transform)
        self.inspector.opacityEdited.connect(self._set_opacity)
        self.inspector.enabledEdited.connect(self._set_enabled)
        self.inspector.lockedEdited.connect(self._set_locked)
        self.inspector.startEdited.connect(self._move_layer_from_inspector)
        self.inspector.durationEdited.connect(self._trim_layer_from_inspector)
        self.inspector.propertyEdited.connect(self._set_property)

        self.playlist.moveRequested.connect(self._move_song)
        self.playlist.removeRequested.connect(self._remove_song)

    def set_document(self, document: ProjectDocument, *, current_path: str = "") -> None:
        self.session.set_document(document)
        self.current_project_path = current_path
        self.preview.clear_accurate_frame()
        self._refresh_all()

    def document(self) -> ProjectDocument:
        return self.session.snapshot()

    def dispatch_external(self, commands, *, message: str = "") -> None:
        self.session.controller.dispatch(commands)
        if message:
            self._set_status(message)
        self._after_edit()

    def _refresh_all(self) -> None:
        doc = self.session.snapshot()
        selected = list(self.session.selected_layer_ids)
        self.timeline.set_document(doc)
        self.timeline.set_selected_layers(selected)
        self.timeline.set_playhead(self.session.playhead_tick)
        self.timeline.set_pixels_per_second(self.session.pixels_per_second)
        self.preview.set_document(doc)
        self.preview.set_selected_layer(selected[0] if len(selected) == 1 else None)
        self.preview.set_playhead(self.session.playhead_tick)
        self.playlist.set_document(doc)
        self._refresh_inspector()
        self.undo_btn.setEnabled(self.session.can_undo)
        self.redo_btn.setEnabled(self.session.can_redo)
        has_selection = bool(selected)
        self.duplicate_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(has_selection)
        self._update_playhead_label()
        dirty = self.session.is_dirty
        if dirty != self._last_dirty:
            self._last_dirty = dirty
            self.dirtyChanged.emit(dirty)
        self.documentChanged.emit(doc)

    def _refresh_inspector(self) -> None:
        layer = self.session.selected_layer()
        if layer is None:
            self.inspector.set_layer(None)
            return
        start = self.session.global_layer_start(layer.layer_id)
        resolved = self.session.resolved()
        item = next((x for x in resolved.layers if x.layer_id == layer.layer_id), None)
        duration = TIMEBASE
        if item and item.intervals:
            first = min(item.intervals, key=lambda interval: interval.start_tick)
            duration = max(1, first.end_tick - first.start_tick)
        self.inspector.set_layer(layer, global_start_tick=start, resolved_duration_tick=duration)

    def _after_edit(self) -> None:
        self.preview.clear_accurate_frame()
        self._refresh_all()

    def _select_layer(self, layer_id) -> None:
        self.session.select_one(layer_id)
        self._refresh_all()

    def set_playhead(self, tick: int) -> None:
        self.session.set_playhead(tick)
        self.timeline.set_playhead(self.session.playhead_tick)
        self.preview.set_playhead(self.session.playhead_tick)
        self._refresh_inspector()
        self._update_playhead_label()

    def _update_playhead_label(self) -> None:
        seconds = self.session.playhead_tick / TIMEBASE
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        self.playhead_label.setText(f"{hours:02d}:{minutes:02d}:{secs:06.3f}")

    def _move_layer(self, layer_id: str, target_tick: int, gesture_pps: float) -> None:
        try:
            target = self.session.snap_tick(target_tick, pixels_per_second=gesture_pps, exclude_layer_id=layer_id)
            self.session.move_layer_global_start(layer_id, target)
            self._after_edit()
        except Exception as exc:
            self._set_status(f"Move gagal: {exc}")

    def _trim_layer(self, layer_id: str, duration_tick: int, gesture_pps: float) -> None:
        try:
            start = self.session.global_layer_start(layer_id)
            snapped_end = self.session.snap_tick(
                start + duration_tick,
                pixels_per_second=gesture_pps,
                exclude_layer_id=layer_id,
            )
            self.session.trim_layer_duration(layer_id, max(1, snapped_end - start))
            self._after_edit()
        except Exception as exc:
            self._set_status(f"Trim gagal: {exc}")

    def _move_layer_from_inspector(self, layer_id: str, target_tick: int) -> None:
        self._move_layer(layer_id, target_tick, self.session.pixels_per_second)

    def _trim_layer_from_inspector(self, layer_id: str, duration_tick: int) -> None:
        try:
            self.session.trim_layer_duration(layer_id, duration_tick)
            self._after_edit()
        except Exception as exc:
            self._set_status(f"Durasi gagal: {exc}")

    def _set_transform(self, layer_id: str, transform) -> None:
        try:
            self.session.set_transform(layer_id, transform)
            self._after_edit()
        except Exception as exc:
            self._set_status(f"Transform gagal: {exc}")

    def _set_opacity(self, layer_id: str, value: float) -> None:
        try:
            self.session.set_opacity(layer_id, value)
            self._after_edit()
        except Exception as exc:
            self._set_status(f"Opacity gagal: {exc}")

    def _set_enabled(self, layer_id: str, value: bool) -> None:
        try:
            self.session.set_enabled(layer_id, value)
            self._after_edit()
        except Exception as exc:
            self._set_status(f"Status layer gagal: {exc}")

    def _set_locked(self, layer_id: str, value: bool) -> None:
        try:
            self.session.set_locked(layer_id, value)
            self._after_edit()
        except Exception as exc:
            self._set_status(f"Lock layer gagal: {exc}")

    def _set_property(self, layer_id: str, key: str, value) -> None:
        try:
            self.session.set_property(layer_id, key, value)
            self._after_edit()
        except Exception as exc:
            self._set_status(f"Properti gagal: {exc}")

    def _set_track_enabled(self, track_id: str, value: bool) -> None:
        try:
            self.session.set_track_enabled(track_id, value)
            self._after_edit()
        except Exception as exc:
            self._set_status(f"Track gagal: {exc}")

    def _set_track_locked(self, track_id: str, value: bool) -> None:
        try:
            self.session.set_track_locked(track_id, value)
            self._after_edit()
        except Exception as exc:
            self._set_status(f"Track gagal: {exc}")

    def _move_song(self, song_id: str, position: int) -> None:
        try:
            self.session.controller.dispatch(MoveSong(song_id, target_position=position))
            self._after_edit()
        except Exception as exc:
            self._set_status(f"Pindah lagu gagal: {exc}")

    def _remove_song(self, song_id: str) -> None:
        try:
            self.session.controller.dispatch(RemoveSong(song_id))
            self._after_edit()
        except Exception as exc:
            self._set_status(f"Hapus lagu gagal: {exc}")

    def use_all_audio(self) -> None:
        try:
            entries = PlaylistServiceV2.use_all_audio(self.session.snapshot())
            self.session.controller.dispatch(SetPlaylistEntries(entries))
            self._after_edit()
            self.tabs.setCurrentWidget(self.playlist)
            self._set_status(f"Playlist memakai {len(entries)} lagu dari Media.")
        except Exception as exc:
            self._set_status(f"Pakai semua lagu gagal: {exc}")

    def auto_arrange(self) -> None:
        try:
            doc = self.session.snapshot()
            fallback = next((asset.asset_id for asset in doc.media if asset.kind in {"image", "video"}), None)
            self.session.controller.dispatch(AutoArrange(AutoArrangeRecipe(fallback_visual_asset_id=fallback)))
            self._after_edit()
            self._set_status("Auto Susun selesai tanpa menghapus layer manual.")
        except Exception as exc:
            self._set_status(f"Auto Susun gagal: {exc}")

    def add_text(self) -> None:
        try:
            self.session.add_text_layer()
            self._after_edit()
        except Exception as exc:
            self._set_status(f"Tambah teks gagal: {exc}")

    def delete_selected(self) -> None:
        try:
            self.session.delete_selected()
            self._after_edit()
        except Exception as exc:
            self._set_status(f"Hapus layer gagal: {exc}")

    def duplicate_selected(self) -> None:
        try:
            self.session.duplicate_selected()
            self._after_edit()
        except Exception as exc:
            self._set_status(f"Duplikat gagal: {exc}")

    def undo(self) -> None:
        self.session.undo()
        self._after_edit()

    def redo(self) -> None:
        self.session.redo()
        self._after_edit()

    def _snap_changed(self, value: bool) -> None:
        self.session.snap_enabled = bool(value)

    def _zoom_changed(self, value: int) -> None:
        self.session.pixels_per_second = float(value)
        self.timeline.set_pixels_per_second(value)

    def _zoom_step(self, direction: int) -> None:
        value = self.zoom_slider.value()
        factor = 1.18 if direction > 0 else 1 / 1.18
        self.zoom_slider.setValue(max(self.zoom_slider.minimum(), min(self.zoom_slider.maximum(), round(value * factor))))

    def toggle_playback(self) -> None:
        if self.play_timer.isActive():
            self.play_timer.stop()
            self.play_btn.setText("▶")
        else:
            if self.session.album_end_tick() <= 0:
                return
            if self.session.playhead_tick >= self.session.album_end_tick():
                self.set_playhead(0)
            self.play_timer.start()
            self.play_btn.setText("⏸")

    def _playback_tick(self) -> None:
        end = self.session.album_end_tick()
        step = max(1, round(TIMEBASE * self.play_timer.interval() / 1000.0))
        target = self.session.playhead_tick + step
        if target >= end:
            self.set_playhead(end)
            self.toggle_playback()
        else:
            self.set_playhead(target)

    def open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Buka Proyek Editor V2", "", "Full Album Project (*.json)")
        if not path:
            return
        if self.session.is_dirty:
            answer = QMessageBox.question(
                self,
                "Perubahan editor belum disimpan",
                "Buka proyek lain dan buang perubahan editor v2 saat ini?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            self.set_document(load_project_document(path), current_path=path)
            self._set_status(f"Proyek v2 dibuka: {Path(path).name}")
        except Exception as exc:
            self._set_status(f"Buka proyek gagal: {exc}")

    def save_project(self) -> bool:
        path = self.current_project_path
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Simpan Proyek Editor V2", "Full_Album_Project_v2.json", "Full Album Project (*.json)")
            if not path:
                return False
        try:
            saved = save_project_document(path, self.session.snapshot())
            self.current_project_path = saved
            self.session.mark_saved()
            self._refresh_all()
            self._set_status(f"Proyek v2 disimpan: {Path(saved).name}")
            return True
        except Exception as exc:
            self._set_status(f"Simpan proyek gagal: {exc}")
            return False

    def render_accurate_preview(self) -> None:
        if self._preview_busy:
            return
        self._preview_busy = True
        self.preview_btn.setEnabled(False)
        snapshot = self.session.snapshot()
        tick = self.session.playhead_tick
        target = temp_dir() / f"preview-v2-{snapshot.project_id}.png"

        def worker() -> None:
            try:
                result = AccuratePreviewService().render_frame(snapshot, tick, target)
                self.bridge.previewReady.emit(result)
            except Exception as exc:
                self.bridge.error.emit(f"Preview akurat gagal: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _preview_ready(self, path: str) -> None:
        self._preview_busy = False
        self.preview_btn.setEnabled(True)
        self.preview.set_accurate_frame(path)
        self._set_status("Preview Akurat diperbarui dari compiler render yang sama.")

    def render_project(self) -> None:
        if self._render_busy:
            return
        destination, _ = QFileDialog.getSaveFileName(
            self,
            "Render Editor V2",
            str(output_dir() / "FULL_ALBUM_FINAL_V2.mp4"),
            "MP4 Video (*.mp4)",
        )
        if not destination:
            return
        self._render_busy = True
        self.render_btn.setEnabled(False)
        snapshot = self.session.snapshot()

        def worker() -> None:
            try:
                result = EditorRenderService().render(snapshot, destination, log=self.bridge.log.emit)
                self.bridge.renderDone.emit(result)
            except Exception as exc:
                self.bridge.error.emit(f"Render v2 gagal: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _render_done(self, path: str) -> None:
        self._render_busy = False
        self.render_btn.setEnabled(True)
        self._set_status(f"Render v2 selesai: {Path(path).name}")

    def _async_error(self, message: str) -> None:
        self._preview_busy = False
        self._render_busy = False
        self.preview_btn.setEnabled(True)
        self.render_btn.setEnabled(True)
        self._set_status(message)

    def _set_status(self, message: str) -> None:
        self.status.setText(str(message))
        self.statusMessage.emit(str(message))

    def keyPressEvent(self, event) -> None:
        focus = self.focusWidget()
        if isinstance(focus, (QLineEdit, QPlainTextEdit, QAbstractSpinBox)):
            return super().keyPressEvent(event)
        modifiers = event.modifiers()
        key = event.key()
        if modifiers & Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_Z:
            self.undo()
            event.accept()
            return
        if modifiers & Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_Y:
            self.redo()
            event.accept()
            return
        if modifiers & Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_D:
            self.duplicate_selected()
            event.accept()
            return
        if key in {Qt.Key.Key_Delete, Qt.Key.Key_Backspace}:
            self.delete_selected()
            event.accept()
            return
        if key == Qt.Key.Key_Space:
            self.toggle_playback()
            event.accept()
            return
        if key in {Qt.Key.Key_Left, Qt.Key.Key_Right}:
            direction = -1 if key == Qt.Key.Key_Left else 1
            self.set_playhead(self.session.playhead_tick + direction * round(TIMEBASE / 10))
            event.accept()
            return
        super().keyPressEvent(event)
