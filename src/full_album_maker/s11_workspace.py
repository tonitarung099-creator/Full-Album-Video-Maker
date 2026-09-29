from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from .cover_manager import CoverAssignmentService, CoverManagerPanel
from .editor_models import ProjectDocument, TIMEBASE
from .editor_session import TimelineScale
from .free_timeline import SetPlaylistTimingMode, SetSongFreeTiming
from .s10_workspace import S10EditorWorkspace
from .timeline_resolver import TimelineResolver


class S11EditorWorkspace(S10EditorWorkspace):
    """S10 workspace plus Free Timeline and v1.1 bulk cover controls."""

    def __init__(
        self,
        document: ProjectDocument | None = None,
        parent=None,
        *,
        custom_template_root=None,
        template_preview_enabled: bool = True,
    ) -> None:
        self._s11_selected_song_id: str | None = None
        super().__init__(
            document,
            parent,
            custom_template_root=custom_template_root,
            template_preview_enabled=template_preview_enabled,
        )
        self._install_free_timeline_controls_s11()
        self.cover_manager_v11 = CoverManagerPanel(self)
        self.tabs.addTab(self.cover_manager_v11, "Cover")
        self.cover_manager_v11.assignRequested.connect(self._assign_covers_v11)
        self.cover_manager_v11.clearRequested.connect(self._clear_covers_v11)
        self.cover_manager_v11.autoMatchRequested.connect(self._auto_match_covers_v11)
        self.cover_manager_v11.set_document(self.session.snapshot())
        self.timeline.songSelected.connect(self._select_song_s11)
        self.timeline.songMoveRequested.connect(self._move_song_timeline_s11)
        self.playlist.table.selectionModel().selectionChanged.connect(
            lambda *_: self._playlist_selection_s11()
        )
        self._refresh_free_controls_s11()

    def _install_free_timeline_controls_s11(self) -> None:
        card = QFrame(self)
        card.setObjectName("freeTimelineCardS11")
        card.setFrameShape(QFrame.Shape.StyledPanel)

        root = QVBoxLayout(card)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(QLabel("Timeline Audio"))
        self.timeline_mode_combo_s11 = QComboBox(card)
        self.timeline_mode_combo_s11.addItem("Rapat / Packed", "packed")
        self.timeline_mode_combo_s11.addItem("Bebas / Free", "free")
        self.timeline_mode_apply_s11 = QPushButton("Ubah Mode", card)
        self.timeline_mode_apply_s11.clicked.connect(self._apply_mode_s11)
        row.addWidget(self.timeline_mode_combo_s11)
        row.addWidget(self.timeline_mode_apply_s11)
        row.addSpacing(8)

        self.song_label_s11 = QLabel("Lagu: belum dipilih", card)
        self.song_label_s11.setMinimumWidth(170)
        row.addWidget(self.song_label_s11, 1)

        row.addWidget(QLabel("Mulai"))
        self.song_start_s11 = QDoubleSpinBox(card)
        self.song_start_s11.setDecimals(3)
        self.song_start_s11.setRange(0.0, 86_400.0)
        self.song_start_s11.setSuffix(" dtk")
        self.song_start_s11.setSingleStep(0.1)
        self.song_start_s11.setMaximumWidth(112)
        row.addWidget(self.song_start_s11)

        row.addWidget(QLabel("Crossfade"))
        self.song_crossfade_s11 = QDoubleSpinBox(card)
        self.song_crossfade_s11.setDecimals(3)
        self.song_crossfade_s11.setRange(0.0, 60.0)
        self.song_crossfade_s11.setSuffix(" dtk")
        self.song_crossfade_s11.setSingleStep(0.1)
        self.song_crossfade_s11.setMaximumWidth(105)
        row.addWidget(self.song_crossfade_s11)

        self.song_timing_apply_s11 = QPushButton("Terapkan Timing", card)
        self.song_timing_apply_s11.clicked.connect(self._apply_song_timing_s11)
        row.addWidget(self.song_timing_apply_s11)
        root.addLayout(row)

        self.free_timeline_status_s11 = QLabel(
            "Packed tetap default. Free mengizinkan gap/silence; overlap wajib crossfade eksplisit.",
            card,
        )
        self.free_timeline_status_s11.setObjectName("muted")
        self.free_timeline_status_s11.setWordWrap(True)
        root.addWidget(self.free_timeline_status_s11)

        layout = self.layout()
        if layout is not None:
            layout.insertWidget(2, card)
        self.free_timeline_card_s11 = card

    def set_document(
        self,
        document: ProjectDocument,
        *,
        current_path: str = "",
    ) -> None:
        super().set_document(document, current_path=current_path)
        self._s11_selected_song_id = None
        if hasattr(self, "timeline_mode_combo_s11"):
            self._refresh_free_controls_s11()
        if hasattr(self, "cover_manager_v11"):
            self.cover_manager_v11.set_document(self.session.snapshot())

    def _after_edit(self) -> None:
        super()._after_edit()
        if hasattr(self, "timeline_mode_combo_s11"):
            self._refresh_free_controls_s11()
        if hasattr(self, "cover_manager_v11"):
            self.cover_manager_v11.set_document(self.session.snapshot())

    def _playlist_selection_s11(self) -> None:
        if not hasattr(self, "song_label_s11"):
            return
        row = self.playlist._selected_row()
        if row is not None:
            self._select_song_s11(row.song_id)

    def _select_song_s11(self, song_id) -> None:
        value = str(song_id or "")
        doc = self.session.snapshot()
        if value not in doc.song_map():
            self._s11_selected_song_id = None
        else:
            self._s11_selected_song_id = value
        self._refresh_free_controls_s11()

    def _refresh_free_controls_s11(self) -> None:
        doc = self.session.snapshot()
        mode_index = self.timeline_mode_combo_s11.findData(doc.playlist.mode)
        self.timeline_mode_combo_s11.blockSignals(True)
        if mode_index >= 0:
            self.timeline_mode_combo_s11.setCurrentIndex(mode_index)
        self.timeline_mode_combo_s11.blockSignals(False)

        song = doc.song_map().get(self._s11_selected_song_id or "")
        free = doc.playlist.mode == "free"
        if song is None:
            self.song_label_s11.setText("Lagu: klik blok audio / baris playlist")
            self.song_start_s11.setValue(0.0)
            self.song_crossfade_s11.setValue(0.0)
        else:
            title = song.display_title.strip() or "Lagu terpilih"
            self.song_label_s11.setText(f"Lagu: {title[:28]}")
            self.song_start_s11.setValue(
                (song.free_start_tick or 0) / TIMEBASE
            )
            self.song_crossfade_s11.setValue(
                song.crossfade_in_tick / TIMEBASE
            )

        timing_enabled = free and song is not None and bool(song.enabled)
        self.song_start_s11.setEnabled(timing_enabled)
        self.song_crossfade_s11.setEnabled(timing_enabled)
        self.song_timing_apply_s11.setEnabled(timing_enabled)

        resolved = TimelineResolver().resolve(doc)
        audio_errors = [
            error for error in resolved.errors if error.startswith("Audio: ")
        ]
        if audio_errors:
            self.free_timeline_status_s11.setText(
                "Timeline Free belum valid: " + " | ".join(audio_errors[:3])
            )
        elif free:
            self.free_timeline_status_s11.setText(
                "Free aktif: gap menjadi silence. Overlap hanya sah bila Crossfade sama persis dengan overlap."
            )
        else:
            self.free_timeline_status_s11.setText(
                "Packed aktif: lagu tetap rapat dan validator lama tetap digunakan."
            )

    def _apply_mode_s11(self) -> None:
        target = str(self.timeline_mode_combo_s11.currentData() or "packed")
        doc = self.session.snapshot()
        if target == doc.playlist.mode:
            self._refresh_free_controls_s11()
            return
        try:
            self.session.controller.dispatch(SetPlaylistTimingMode(target))
            if target == "free" and not self._s11_selected_song_id:
                first = next(
                    (song for song in self.session.snapshot().playlist.entries if song.enabled),
                    None,
                )
                if first is not None:
                    self._s11_selected_song_id = first.song_id
            self._after_edit()
            self._set_status(
                "Free Timeline aktif; posisi packed dipertahankan."
                if target == "free"
                else "Timeline kembali Packed; gap/crossfade dikompakkan dan dibersihkan."
            )
        except Exception as exc:
            self._set_status(f"Ubah mode timeline gagal: {exc}")
            self._refresh_free_controls_s11()

    def _apply_song_timing_s11(self) -> None:
        song_id = self._s11_selected_song_id
        if not song_id:
            return
        start_tick = int(round(self.song_start_s11.value() * TIMEBASE))
        fade_tick = int(round(self.song_crossfade_s11.value() * TIMEBASE))
        try:
            self.session.controller.dispatch(
                SetSongFreeTiming(song_id, start_tick, fade_tick)
            )
            self._after_edit()
            self._set_status("Timing lagu Free Timeline diterapkan.")
        except Exception as exc:
            self._set_status(f"Timing lagu ditolak: {exc}")
            self._refresh_free_controls_s11()

    def _snap_song_tick_s11(
        self,
        song_id: str,
        target_tick: int,
        pixels_per_second: float,
    ) -> int:
        value = max(0, int(target_tick))
        if not self.session.snap_enabled:
            return value
        resolved = self.session.resolved()
        candidates = {0, resolved.duration_tick}
        for song in resolved.songs:
            if song.song_id == song_id:
                continue
            candidates.add(song.start_tick)
            candidates.add(song.end_tick)
        for layer in resolved.layers:
            for interval in layer.intervals:
                candidates.add(interval.start_tick)
                candidates.add(interval.end_tick)
        scale = TimelineScale(pixels_per_second)
        threshold = abs(scale.delta_px_to_tick(self.session.snap_threshold_px))
        nearest = min(candidates, key=lambda item: abs(item - value))
        return nearest if abs(nearest - value) <= threshold else value

    def _move_song_timeline_s11(
        self,
        song_id: str,
        target_tick: int,
        gesture_pps: float,
    ) -> None:
        doc = self.session.snapshot()
        song = doc.song_map().get(song_id)
        if song is None or doc.playlist.mode != "free":
            return
        target = self._snap_song_tick_s11(song_id, target_tick, gesture_pps)
        try:
            self.session.controller.dispatch(
                SetSongFreeTiming(
                    song_id,
                    target,
                    song.crossfade_in_tick,
                )
            )
            self._s11_selected_song_id = song_id
            self._after_edit()
            self._set_status("Posisi lagu Free Timeline dipindahkan.")
        except Exception as exc:
            self._set_status(
                "Pindah lagu ditolak; atur Crossfade bila ingin overlap: " + str(exc)
            )
            self._refresh_free_controls_s11()

    def _assign_covers_v11(self, song_ids, asset_id: str) -> None:
        try:
            commands = CoverAssignmentService.bulk_commands(
                self.session.snapshot(), list(song_ids), asset_id
            )
            if not commands:
                self._set_status("Cover terpilih sudah terpasang pada semua lagu yang dipilih.")
                return
            self.session.controller.dispatch(commands)
            count = len(commands)
            self._after_edit()
            self._set_status(
                f"Cover dipasang ke {count} lagu sebagai satu transaksi Undo."
            )
        except Exception as exc:
            self._set_status(f"Pasang cover massal gagal: {exc}")

    def _clear_covers_v11(self, song_ids) -> None:
        try:
            commands = CoverAssignmentService.bulk_commands(
                self.session.snapshot(), list(song_ids), None
            )
            if not commands:
                self._set_status("Lagu terpilih sudah tidak memiliki cover khusus.")
                return
            self.session.controller.dispatch(commands)
            count = len(commands)
            self._after_edit()
            self._set_status(
                f"Cover khusus dihapus dari {count} lagu sebagai satu transaksi Undo."
            )
        except Exception as exc:
            self._set_status(f"Hapus cover massal gagal: {exc}")

    def _auto_match_covers_v11(self, only_empty: bool) -> None:
        try:
            commands, report = CoverAssignmentService.auto_match_commands(
                self.session.snapshot(), only_empty=bool(only_empty)
            )
            if commands:
                self.session.controller.dispatch(commands)
                self._after_edit()
            self._set_status(
                "Cocokkan cover selesai: "
                f"{len(commands)} dipasang, "
                f"{len(report.unmatched_song_ids)} tidak cocok, "
                f"{len(report.ambiguous_song_ids)} ambigu, "
                f"{len(report.skipped_existing_song_ids)} cover lama dipertahankan."
            )
        except Exception as exc:
            self._set_status(f"Cocokkan cover gagal: {exc}")
