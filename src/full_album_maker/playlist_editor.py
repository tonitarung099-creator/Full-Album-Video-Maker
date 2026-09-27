from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QMimeData, QModelIndex, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from .editor_models import ProjectDocument, TIMEBASE
from .playlist_service_v2 import PlaylistRow, PlaylistServiceV2


class PlaylistTableModel(QAbstractTableModel):
    SongIdRole = int(Qt.ItemDataRole.UserRole) + 1
    MIME_TYPE = "application/x-full-album-maker-song-id"
    moveRequested = Signal(str, int)

    HEADERS = ("#", "Judul", "Artist", "Durasi")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._document = ProjectDocument.new_empty()
        self._query = ""
        self._rows: list[PlaylistRow] = []

    @property
    def query(self) -> str:
        return self._query

    @property
    def reorder_allowed(self) -> bool:
        return PlaylistServiceV2.reorder_allowed(self._query)

    def set_document(self, document: ProjectDocument) -> None:
        self.beginResetModel()
        self._document = document.clone()
        self._rows = PlaylistServiceV2.rows(self._document, self._query)
        self.endResetModel()

    def set_filter_text(self, text: str) -> None:
        self.beginResetModel()
        self._query = str(text or "")
        self._rows = PlaylistServiceV2.rows(self._document, self._query)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self.HEADERS):
                return self.HEADERS[section]
        return None

    @staticmethod
    def _duration_text(duration_tick: int) -> str:
        seconds = max(0, duration_tick) / TIMEBASE
        minutes = int(seconds // 60)
        remain = seconds - minutes * 60
        return f"{minutes:02d}:{remain:05.2f}"

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        if role == self.SongIdRole:
            return row.song_id
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        values = (row.position, row.title, row.artist, self._duration_text(row.duration_tick))
        return values[index.column()] if 0 <= index.column() < len(values) else None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.ItemIsDropEnabled if self.reorder_allowed else Qt.ItemFlag.NoItemFlags
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if self.reorder_allowed:
            base |= Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled
        return base

    def mimeTypes(self) -> list[str]:
        return [self.MIME_TYPE]

    def mimeData(self, indexes) -> QMimeData:
        mime = QMimeData()
        rows = sorted({index.row() for index in indexes if index.isValid()})
        if len(rows) == 1 and 0 <= rows[0] < len(self._rows):
            mime.setData(self.MIME_TYPE, self._rows[rows[0]].song_id.encode("utf-8"))
        return mime

    def supportedDropActions(self):
        return Qt.DropAction.MoveAction

    def dropMimeData(self, data, action, row, column, parent):
        if action == Qt.DropAction.IgnoreAction:
            return True
        if action != Qt.DropAction.MoveAction or not self.reorder_allowed:
            return False
        if not data.hasFormat(self.MIME_TYPE):
            return False
        try:
            song_id = bytes(data.data(self.MIME_TYPE)).decode("utf-8")
        except Exception:
            return False
        if row < 0:
            row = parent.row() if parent.isValid() else len(self._rows)
        target_position = max(1, min(row + 1, len(self._rows)))
        self.moveRequested.emit(song_id, target_position)
        return True

    def row_at(self, model_row: int) -> PlaylistRow | None:
        if 0 <= model_row < len(self._rows):
            return self._rows[model_row]
        return None


class PlaylistPanel(QWidget):
    """Standalone v2 playlist panel; MainWindow supplies controller wiring later."""

    moveRequested = Signal(str, int)
    removeRequested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Cari judul, artist, atau nama file…")
        self.model = PlaylistTableModel(self)
        self.table = QTableView(self)
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.table.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.table.setDropIndicatorShown(True)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        self.up_button = QPushButton("Naik", self)
        self.down_button = QPushButton("Turun", self)
        self.move_button = QPushButton("Pindah ke…", self)
        self.remove_button = QPushButton("Hapus dari Playlist", self)

        buttons = QHBoxLayout()
        buttons.addWidget(self.up_button)
        buttons.addWidget(self.down_button)
        buttons.addWidget(self.move_button)
        buttons.addWidget(self.remove_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.search)
        layout.addWidget(self.table, 1)
        layout.addLayout(buttons)

        self.search.textChanged.connect(self._filter_changed)
        self.model.moveRequested.connect(self.moveRequested.emit)
        self.up_button.clicked.connect(lambda: self._move_relative(-1))
        self.down_button.clicked.connect(lambda: self._move_relative(1))
        self.move_button.clicked.connect(self._move_explicit)
        self.remove_button.clicked.connect(self._remove_selected)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._refresh_buttons())
        self._refresh_buttons()

    def set_document(self, document: ProjectDocument) -> None:
        self.model.set_document(document)
        self._refresh_buttons()

    def _filter_changed(self, text: str) -> None:
        self.model.set_filter_text(text)
        self._refresh_buttons()

    def _selected_row(self) -> PlaylistRow | None:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return None
        return self.model.row_at(indexes[0].row())

    def _refresh_buttons(self) -> None:
        row = self._selected_row()
        selected = row is not None
        reorder = selected and self.model.reorder_allowed
        total = len(self._document_playlist_rows())
        self.up_button.setEnabled(reorder and bool(row and row.position > 1))
        self.down_button.setEnabled(reorder and bool(row and row.position < total))
        self.move_button.setEnabled(selected)
        self.remove_button.setEnabled(selected)

    def _document_playlist_rows(self) -> list[PlaylistRow]:
        return PlaylistServiceV2.rows(self.model._document)

    def _move_relative(self, delta: int) -> None:
        row = self._selected_row()
        if row is None or not self.model.reorder_allowed:
            return
        target = row.position + delta
        if 1 <= target <= len(self._document_playlist_rows()):
            self.moveRequested.emit(row.song_id, target)

    def _move_explicit(self) -> None:
        row = self._selected_row()
        total = len(self._document_playlist_rows())
        if row is None or total <= 0:
            return
        target, accepted = QInputDialog.getInt(
            self,
            "Pindah Lagu",
            "Nomor posisi global:",
            row.position,
            1,
            total,
            1,
        )
        if accepted:
            self.moveRequested.emit(row.song_id, target)

    def _remove_selected(self) -> None:
        row = self._selected_row()
        if row is not None:
            self.removeRequested.emit(row.song_id)
