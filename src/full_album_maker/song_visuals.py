from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .cover_manager import normalize_cover_key
from .editor_commands import CommandError
from .editor_models import Layer, MediaAsset, ProjectDocument, TimeBinding, Transform
from .playlist_commands import SetSongVisual


SONG_VISUAL_TRANSITIONS = {
    "cut": "Cut",
    "fade": "Fade",
    "slide_left": "Slide Kiri",
    "slide_right": "Slide Kanan",
}

SONG_VISUAL_MOTIONS = {
    "static": "Static",
    "zoom_in": "Zoom In",
    "zoom_out": "Zoom Out",
    "pan_left": "Pan Left",
    "pan_right": "Pan Right",
}

SONG_VISUAL_PLAYBACK = {
    "loop": "Loop Video",
    "freeze": "Freeze Frame",
}


def normalize_song_visual_properties(properties: dict[str, Any] | None) -> dict[str, Any]:
    source = dict(properties or {})
    fit = str(source.get("fit", "fill"))
    motion = str(source.get("image_motion", "zoom_in"))
    playback = str(source.get("video_playback", "loop"))
    transition = str(source.get("transition", "fade"))
    transition_seconds = float(source.get("transition_seconds", 0.8))

    if fit not in {"fill", "fit"}:
        raise ValueError("Fit Visual Lagu harus fill/fit.")
    if motion not in SONG_VISUAL_MOTIONS:
        raise ValueError("Motion foto Visual Lagu belum didukung.")
    if playback not in SONG_VISUAL_PLAYBACK:
        raise ValueError("Playback video Visual Lagu harus loop/freeze.")
    if transition not in SONG_VISUAL_TRANSITIONS:
        raise ValueError("Transisi Visual Lagu belum didukung.")
    if not 0.0 <= transition_seconds <= 5.0:
        raise ValueError("Durasi transisi Visual Lagu harus 0..5 detik.")
    if transition == "cut":
        transition_seconds = 0.0

    return {
        "fit": fit,
        "image_motion": motion,
        "video_playback": playback,
        "transition": transition,
        "transition_seconds": transition_seconds,
    }


def make_song_visual_layer(track_id: str, order: int = 5) -> Layer:
    return Layer(
        track_id=track_id,
        type="song_visual",
        name="Visual Lagu Dinamis",
        order=max(0, int(order)),
        time_binding=TimeBinding(kind="album"),
        transform=Transform(x=0.0, y=0.0, width=1.0, height=1.0),
        properties=normalize_song_visual_properties({}),
        origin="manual",
    )


def _asset_name(asset: MediaAsset) -> str:
    return str(asset.original_name or Path(asset.locator).name or asset.asset_id)


@dataclass(frozen=True)
class SongVisualAutoMatchReport:
    matches: dict[str, str]
    unmatched_song_ids: tuple[str, ...]
    ambiguous_song_ids: tuple[str, ...]
    skipped_existing_song_ids: tuple[str, ...]


class SongVisualAssignmentService:
    @staticmethod
    def visual_assets(document: ProjectDocument) -> list[MediaAsset]:
        return [asset for asset in document.media if asset.kind in {"image", "video"}]

    @staticmethod
    def bulk_commands(
        document: ProjectDocument,
        song_ids: list[str] | tuple[str, ...],
        asset_id: str | None,
    ) -> list[SetSongVisual]:
        songs = document.song_map()
        if asset_id is not None:
            asset = document.asset_map().get(asset_id)
            if asset is None:
                raise CommandError("Asset visual lagu tidak ditemukan.")
            if asset.kind not in {"image", "video"}:
                raise CommandError("Visual lagu harus berupa image/video.")

        unique: list[str] = []
        seen: set[str] = set()
        for song_id in song_ids:
            value = str(song_id)
            if value in seen:
                continue
            seen.add(value)
            if value not in songs:
                raise CommandError("Lagu tidak ditemukan.")
            unique.append(value)

        return [
            SetSongVisual(song_id, asset_id)
            for song_id in unique
            if songs[song_id].visual_asset_id != asset_id
        ]

    @staticmethod
    def auto_match(document: ProjectDocument, *, only_empty: bool = True) -> SongVisualAutoMatchReport:
        visuals = SongVisualAssignmentService.visual_assets(document)
        visuals_by_key: dict[str, list[str]] = {}
        for asset in visuals:
            key = normalize_cover_key(_asset_name(asset))
            if key:
                visuals_by_key.setdefault(key, []).append(asset.asset_id)

        assets = document.asset_map()
        song_keys: dict[str, tuple[str, ...]] = {}
        songs_by_key: dict[str, list[str]] = {}
        skipped_existing: list[str] = []
        for song in document.playlist.entries:
            if only_empty and song.visual_asset_id:
                skipped_existing.append(song.song_id)
                continue
            keys: list[str] = []
            title_key = normalize_cover_key(song.display_title)
            if title_key:
                keys.append(title_key)
            audio = assets.get(song.asset_id)
            if audio is not None:
                source_key = normalize_cover_key(_asset_name(audio))
                if source_key and source_key not in keys:
                    keys.append(source_key)
            song_keys[song.song_id] = tuple(keys)
            for key in keys:
                songs_by_key.setdefault(key, []).append(song.song_id)

        matches: dict[str, str] = {}
        unmatched: list[str] = []
        ambiguous: list[str] = []
        for song in document.playlist.entries:
            keys = song_keys.get(song.song_id)
            if keys is None:
                continue
            candidates: set[str] = set()
            ambiguous_key = False
            for key in keys:
                visual_candidates = visuals_by_key.get(key, [])
                song_candidates = songs_by_key.get(key, [])
                if len(visual_candidates) > 1 or len(song_candidates) > 1:
                    if visual_candidates:
                        ambiguous_key = True
                    continue
                if len(visual_candidates) == 1 and len(song_candidates) == 1:
                    candidates.add(visual_candidates[0])
            if len(candidates) == 1 and not ambiguous_key:
                matches[song.song_id] = next(iter(candidates))
            elif len(candidates) > 1 or ambiguous_key:
                ambiguous.append(song.song_id)
            else:
                unmatched.append(song.song_id)

        return SongVisualAutoMatchReport(
            matches=matches,
            unmatched_song_ids=tuple(unmatched),
            ambiguous_song_ids=tuple(ambiguous),
            skipped_existing_song_ids=tuple(skipped_existing),
        )

    @staticmethod
    def auto_match_commands(
        document: ProjectDocument, *, only_empty: bool = True
    ) -> tuple[list[SetSongVisual], SongVisualAutoMatchReport]:
        report = SongVisualAssignmentService.auto_match(document, only_empty=only_empty)
        commands = [
            SetSongVisual(song.song_id, report.matches[song.song_id])
            for song in document.playlist.entries
            if song.song_id in report.matches
            and song.visual_asset_id != report.matches[song.song_id]
        ]
        return commands, report


class SongVisualManagerPanel(QWidget):
    assignRequested = Signal(object, str)
    clearRequested = Signal(object)
    autoMatchRequested = Signal(bool)
    styleRequested = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._document = ProjectDocument.new_empty()

        guide = QLabel(
            "Pilih foto/video per lagu. Cocokkan Nama hanya memakai nama yang cocok tepat; kasus ambigu tidak ditebak.",
            self,
        )
        guide.setWordWrap(True)
        guide.setObjectName("muted")

        self.table = QTableWidget(self)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["#", "Lagu", "Artist", "Visual"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.visual_combo = QComboBox(self)
        self.assign_button = QPushButton("Pasang ke Terpilih", self)
        self.clear_button = QPushButton("Hapus Terpilih", self)
        self.auto_button = QPushButton("Cocokkan Nama", self)
        self.only_empty = QCheckBox("Hanya yang kosong", self)
        self.only_empty.setChecked(True)

        assignment = QHBoxLayout()
        assignment.addWidget(self.visual_combo, 1)
        assignment.addWidget(self.assign_button)
        assignment.addWidget(self.clear_button)
        assignment.addWidget(self.auto_button)
        assignment.addWidget(self.only_empty)

        self.fit_combo = QComboBox(self)
        self.fit_combo.addItem("Fill", "fill")
        self.fit_combo.addItem("Fit", "fit")
        self.motion_combo = QComboBox(self)
        for value, label in SONG_VISUAL_MOTIONS.items():
            self.motion_combo.addItem(label, value)
        self.playback_combo = QComboBox(self)
        for value, label in SONG_VISUAL_PLAYBACK.items():
            self.playback_combo.addItem(label, value)
        self.transition_combo = QComboBox(self)
        for value, label in SONG_VISUAL_TRANSITIONS.items():
            self.transition_combo.addItem(label, value)
        self.transition_seconds = QDoubleSpinBox(self)
        self.transition_seconds.setRange(0.0, 5.0)
        self.transition_seconds.setDecimals(2)
        self.transition_seconds.setSingleStep(0.1)
        self.transition_seconds.setValue(0.8)
        self.transition_seconds.setSuffix(" dtk")
        self.apply_style_button = QPushButton("Terapkan Gaya Visual", self)

        style = QHBoxLayout()
        style.addWidget(QLabel("Fit"))
        style.addWidget(self.fit_combo)
        style.addWidget(QLabel("Foto"))
        style.addWidget(self.motion_combo)
        style.addWidget(QLabel("Video"))
        style.addWidget(self.playback_combo)
        style.addWidget(QLabel("Transisi"))
        style.addWidget(self.transition_combo)
        style.addWidget(self.transition_seconds)
        style.addWidget(self.apply_style_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        layout.addWidget(guide)
        layout.addWidget(self.table, 1)
        layout.addLayout(assignment)
        layout.addLayout(style)

        self.assign_button.clicked.connect(self._request_assign)
        self.clear_button.clicked.connect(self._request_clear)
        self.auto_button.clicked.connect(
            lambda: self.autoMatchRequested.emit(self.only_empty.isChecked())
        )
        self.apply_style_button.clicked.connect(self._request_style)
        self.table.itemSelectionChanged.connect(self._refresh_buttons)
        self.visual_combo.currentIndexChanged.connect(self._refresh_buttons)
        self.transition_combo.currentIndexChanged.connect(self._sync_transition_control)
        self._sync_transition_control()
        self._refresh_buttons()

    def set_document(self, document: ProjectDocument) -> None:
        self._document = document.clone()
        assets = self._document.asset_map()
        self.table.clearSelection()
        self.table.setRowCount(len(self._document.playlist.entries))
        for row_index, song in enumerate(self._document.playlist.entries):
            number = QTableWidgetItem(str(row_index + 1))
            number.setData(Qt.ItemDataRole.UserRole, song.song_id)
            audio = assets.get(song.asset_id)
            title = song.display_title or (_asset_name(audio) if audio else "(Tanpa judul)")
            artist = song.display_artist or "—"
            visual = assets.get(song.visual_asset_id or "")
            visual_text = _asset_name(visual) if visual else "—"
            for column, value in enumerate((number, title, artist, visual_text)):
                item = value if isinstance(value, QTableWidgetItem) else QTableWidgetItem(str(value))
                self.table.setItem(row_index, column, item)

        current = str(self.visual_combo.currentData() or "")
        self.visual_combo.blockSignals(True)
        try:
            self.visual_combo.clear()
            for asset in SongVisualAssignmentService.visual_assets(self._document):
                kind = "Foto" if asset.kind == "image" else "Video"
                self.visual_combo.addItem(f"[{kind}] {_asset_name(asset)}", asset.asset_id)
            index = self.visual_combo.findData(current)
            if index >= 0:
                self.visual_combo.setCurrentIndex(index)
        finally:
            self.visual_combo.blockSignals(False)

        layer = next((item for item in self._document.layers if item.type == "song_visual"), None)
        if layer is not None:
            try:
                props = normalize_song_visual_properties(layer.properties)
            except Exception:
                props = normalize_song_visual_properties({})
            for combo, value in (
                (self.fit_combo, props["fit"]),
                (self.motion_combo, props["image_motion"]),
                (self.playback_combo, props["video_playback"]),
                (self.transition_combo, props["transition"]),
            ):
                idx = combo.findData(value)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            self.transition_seconds.setValue(props["transition_seconds"])
        self._sync_transition_control()
        self._refresh_buttons()

    def selected_song_ids(self) -> list[str]:
        result: list[str] = []
        for index in self.table.selectionModel().selectedRows(0):
            item = self.table.item(index.row(), 0)
            value = str(item.data(Qt.ItemDataRole.UserRole) or "") if item else ""
            if value and value not in result:
                result.append(value)
        return result

    def _sync_transition_control(self, *_args) -> None:
        self.transition_seconds.setEnabled(self.transition_combo.currentData() != "cut")

    def _refresh_buttons(self, *_args) -> None:
        selected = bool(self.selected_song_ids())
        self.assign_button.setEnabled(selected and self.visual_combo.count() > 0)
        self.clear_button.setEnabled(selected)
        self.auto_button.setEnabled(
            bool(self._document.playlist.entries)
            and bool(SongVisualAssignmentService.visual_assets(self._document))
        )

    def _request_assign(self) -> None:
        song_ids = self.selected_song_ids()
        asset_id = str(self.visual_combo.currentData() or "")
        if song_ids and asset_id:
            self.assignRequested.emit(song_ids, asset_id)

    def _request_clear(self) -> None:
        song_ids = self.selected_song_ids()
        if song_ids:
            self.clearRequested.emit(song_ids)

    def _request_style(self) -> None:
        props = normalize_song_visual_properties(
            {
                "fit": self.fit_combo.currentData(),
                "image_motion": self.motion_combo.currentData(),
                "video_playback": self.playback_combo.currentData(),
                "transition": self.transition_combo.currentData(),
                "transition_seconds": self.transition_seconds.value(),
            }
        )
        self.styleRequested.emit(props)
