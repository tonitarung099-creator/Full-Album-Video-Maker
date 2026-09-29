from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .editor_commands import CommandError
from .editor_models import MediaAsset, ProjectDocument
from .playlist_commands import SetSongCover


_MEDIA_EXTENSIONS = {
    ".aac",
    ".flac",
    ".jpeg",
    ".jpg",
    ".m4a",
    ".mp3",
    ".ogg",
    ".opus",
    ".png",
    ".wav",
    ".webp",
}


def normalize_cover_key(value: str) -> str:
    """Normalize a title/file name for conservative exact cover matching.

    This intentionally does not perform fuzzy matching. A leading track number is
    removed only when it is followed by a filename-style separator. Known media
    extensions are stripped, while dots in real titles such as "Mr. Brightside"
    remain part of the title before punctuation normalization.
    """

    raw = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not raw:
        return ""
    path = Path(raw)
    if path.suffix.casefold() in _MEDIA_EXTENSIONS:
        raw = path.stem
    raw = re.sub(r"^\s*\d{1,3}\s*(?:[-_.]+\s*)", "", raw)
    raw = raw.casefold()
    raw = re.sub(r"[_\W]+", " ", raw, flags=re.UNICODE)
    return " ".join(raw.split())


def _asset_name(asset: MediaAsset) -> str:
    return str(asset.original_name or Path(asset.locator).name or asset.asset_id)


@dataclass(frozen=True)
class CoverAutoMatchReport:
    matches: dict[str, str]
    unmatched_song_ids: tuple[str, ...]
    ambiguous_song_ids: tuple[str, ...]
    skipped_existing_song_ids: tuple[str, ...]

    @property
    def matched_count(self) -> int:
        return len(self.matches)


class CoverAssignmentService:
    """Pure cover assignment logic keyed by stable song_id / asset_id."""

    @staticmethod
    def image_assets(document: ProjectDocument) -> list[MediaAsset]:
        return [asset for asset in document.media if asset.kind == "image"]

    @staticmethod
    def asset_label(asset: MediaAsset) -> str:
        return _asset_name(asset)

    @staticmethod
    def bulk_commands(
        document: ProjectDocument,
        song_ids: list[str] | tuple[str, ...],
        asset_id: str | None,
    ) -> list[SetSongCover]:
        songs = document.song_map()
        if asset_id is not None:
            asset = document.asset_map().get(asset_id)
            if asset is None:
                raise CommandError("Asset cover tidak ditemukan.")
            if asset.kind != "image":
                raise CommandError("Cover lagu harus berupa image.")

        ordered_ids: list[str] = []
        seen: set[str] = set()
        for song_id in song_ids:
            song_id = str(song_id)
            if song_id in seen:
                continue
            seen.add(song_id)
            if song_id not in songs:
                raise CommandError("Lagu tidak ditemukan.")
            ordered_ids.append(song_id)

        return [
            SetSongCover(song_id, asset_id)
            for song_id in ordered_ids
            if songs[song_id].cover_asset_id != asset_id
        ]

    @staticmethod
    def auto_match(document: ProjectDocument, *, only_empty: bool = True) -> CoverAutoMatchReport:
        images = CoverAssignmentService.image_assets(document)
        image_ids_by_key: dict[str, list[str]] = {}
        for asset in images:
            key = normalize_cover_key(_asset_name(asset))
            if key:
                image_ids_by_key.setdefault(key, []).append(asset.asset_id)

        assets = document.asset_map()
        song_keys: dict[str, tuple[str, ...]] = {}
        song_ids_by_key: dict[str, list[str]] = {}
        skipped_existing: list[str] = []

        for song in document.playlist.entries:
            if only_empty and song.cover_asset_id:
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
                song_ids_by_key.setdefault(key, []).append(song.song_id)

        matches: dict[str, str] = {}
        unmatched: list[str] = []
        ambiguous: list[str] = []
        for song in document.playlist.entries:
            if song.song_id not in song_keys:
                continue
            candidates: set[str] = set()
            had_ambiguous_key = False
            for key in song_keys[song.song_id]:
                image_candidates = image_ids_by_key.get(key, [])
                song_candidates = song_ids_by_key.get(key, [])
                if len(image_candidates) > 1 or len(song_candidates) > 1:
                    if image_candidates:
                        had_ambiguous_key = True
                    continue
                if len(image_candidates) == 1 and len(song_candidates) == 1:
                    candidates.add(image_candidates[0])
            if len(candidates) == 1 and not had_ambiguous_key:
                matches[song.song_id] = next(iter(candidates))
            elif len(candidates) > 1 or had_ambiguous_key:
                ambiguous.append(song.song_id)
            else:
                unmatched.append(song.song_id)

        return CoverAutoMatchReport(
            matches=matches,
            unmatched_song_ids=tuple(unmatched),
            ambiguous_song_ids=tuple(ambiguous),
            skipped_existing_song_ids=tuple(skipped_existing),
        )

    @staticmethod
    def auto_match_commands(
        document: ProjectDocument, *, only_empty: bool = True
    ) -> tuple[list[SetSongCover], CoverAutoMatchReport]:
        report = CoverAssignmentService.auto_match(document, only_empty=only_empty)
        assignments = [
            SetSongCover(song.song_id, report.matches[song.song_id])
            for song in document.playlist.entries
            if song.song_id in report.matches
            and song.cover_asset_id != report.matches[song.song_id]
        ]
        return assignments, report


class CoverManagerPanel(QWidget):
    """Bulk cover assignment UI kept separate from playlist drag/drop semantics."""

    assignRequested = Signal(object, str)
    clearRequested = Signal(object)
    autoMatchRequested = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._document = ProjectDocument.new_empty()

        guide = QLabel(
            "Pilih satu atau beberapa lagu. Pencocokan otomatis hanya memakai nama yang cocok tepat; hasil ambigu tidak ditebak.",
            self,
        )
        guide.setWordWrap(True)
        guide.setObjectName("muted")

        self.table = QTableWidget(self)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["#", "Lagu", "Artist", "Cover"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.cover_combo = QComboBox(self)
        self.cover_combo.setMinimumWidth(140)
        self.assign_button = QPushButton("Pasang ke Terpilih", self)
        self.clear_button = QPushButton("Hapus Terpilih", self)
        self.auto_button = QPushButton("Cocokkan Nama", self)
        self.only_empty = QCheckBox("Hanya yang kosong", self)
        self.only_empty.setChecked(True)

        controls = QHBoxLayout()
        controls.addWidget(self.cover_combo, 1)
        controls.addWidget(self.assign_button)
        controls.addWidget(self.clear_button)
        controls.addWidget(self.auto_button)
        controls.addWidget(self.only_empty)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        layout.addWidget(guide)
        layout.addWidget(self.table, 1)
        layout.addLayout(controls)

        self.assign_button.clicked.connect(self._request_assign)
        self.clear_button.clicked.connect(self._request_clear)
        self.auto_button.clicked.connect(
            lambda: self.autoMatchRequested.emit(self.only_empty.isChecked())
        )
        self.table.itemSelectionChanged.connect(self._refresh_buttons)
        self.cover_combo.currentIndexChanged.connect(self._refresh_buttons)
        self._refresh_buttons()

    def set_document(self, document: ProjectDocument) -> None:
        self._document = document.clone()
        assets = self._document.asset_map()

        self.table.clearSelection()
        self.table.setRowCount(len(self._document.playlist.entries))
        for row_index, song in enumerate(self._document.playlist.entries):
            number = QTableWidgetItem(str(row_index + 1))
            number.setData(Qt.ItemDataRole.UserRole, song.song_id)
            title = song.display_title
            if not title:
                audio = assets.get(song.asset_id)
                title = _asset_name(audio) if audio is not None else "(Tanpa judul)"
            artist = song.display_artist or "—"
            cover = assets.get(song.cover_asset_id or "")
            cover_text = _asset_name(cover) if cover is not None else "—"
            for column, value in enumerate((number, title, artist, cover_text)):
                item = value if isinstance(value, QTableWidgetItem) else QTableWidgetItem(str(value))
                self.table.setItem(row_index, column, item)

        current_asset = str(self.cover_combo.currentData() or "")
        self.cover_combo.blockSignals(True)
        try:
            self.cover_combo.clear()
            for asset in CoverAssignmentService.image_assets(self._document):
                self.cover_combo.addItem(CoverAssignmentService.asset_label(asset), asset.asset_id)
            index = self.cover_combo.findData(current_asset)
            if index >= 0:
                self.cover_combo.setCurrentIndex(index)
        finally:
            self.cover_combo.blockSignals(False)
        self._refresh_buttons()

    def selected_song_ids(self) -> list[str]:
        ids: list[str] = []
        for index in self.table.selectionModel().selectedRows(0):
            item = self.table.item(index.row(), 0)
            song_id = str(item.data(Qt.ItemDataRole.UserRole) or "") if item else ""
            if song_id and song_id not in ids:
                ids.append(song_id)
        return ids

    def _refresh_buttons(self, *_args) -> None:
        selected = bool(self.selected_song_ids())
        self.assign_button.setEnabled(selected and self.cover_combo.count() > 0)
        self.clear_button.setEnabled(selected)
        self.auto_button.setEnabled(
            bool(self._document.playlist.entries)
            and bool(CoverAssignmentService.image_assets(self._document))
        )

    def _request_assign(self) -> None:
        song_ids = self.selected_song_ids()
        asset_id = str(self.cover_combo.currentData() or "")
        if song_ids and asset_id:
            self.assignRequested.emit(song_ids, asset_id)

    def _request_clear(self) -> None:
        song_ids = self.selected_song_ids()
        if song_ids:
            self.clearRequested.emit(song_ids)
