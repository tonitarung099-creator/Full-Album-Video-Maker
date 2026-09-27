from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QLabel, QSizePolicy, QWidget

from .editor_models import ProjectDocument
from .editor_workspace import EditorWorkspace


class ResponsiveEditorWorkspace(EditorWorkspace):
    """EditorWorkspace with compact controls for laptop layouts.

    The base workspace owns all actions/signals. This class only changes their
    presentation so the center editor can coexist with Media + AI panels on a
    1366px desktop without clipping or overlap.
    """

    def __init__(self, document: ProjectDocument | None = None, parent=None) -> None:
        super().__init__(document, parent)
        self._rebuild_compact_toolbar()
        self._rebuild_compact_playlist_controls()

    def _rebuild_compact_toolbar(self) -> None:
        root = self.layout()
        if root is None or root.count() == 0:
            return

        old_item = root.takeAt(0)
        old_layout = old_item.layout()
        if old_layout is None:
            return

        known = {
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
            self.snap_check,
            self.zoom_slider,
        }

        while old_layout.count():
            item = old_layout.takeAt(0)
            widget = item.widget()
            if widget is not None and widget not in known:
                widget.deleteLater()

        toolbar = QWidget(self)
        toolbar.setObjectName("editorToolbarCompact")
        toolbar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        grid = QGridLayout(toolbar)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(4)

        rows = [
            [self.open_btn, self.save_btn, self.undo_btn, self.redo_btn],
            [self.add_text_btn, self.duplicate_btn, self.delete_btn, self.use_all_btn],
            [self.auto_btn, self.play_btn, self.preview_btn, self.render_btn],
        ]

        self.use_all_btn.setText("Semua Lagu")
        self.preview_btn.setText("Preview Akurat")
        self.render_btn.setText("Render V2")

        for row, widgets in enumerate(rows):
            for column, widget in enumerate(widgets):
                grid.addWidget(widget, row, column)

        grid.addWidget(self.snap_check, 3, 0)
        zoom_label = QLabel("Zoom", toolbar)
        grid.addWidget(zoom_label, 3, 1)
        grid.addWidget(self.zoom_slider, 3, 2, 1, 2)
        grid.setColumnStretch(3, 1)

        root.insertWidget(0, toolbar)
        self.compact_toolbar = toolbar

    def _rebuild_compact_playlist_controls(self) -> None:
        root = self.playlist.layout()
        if root is None or root.count() < 3:
            return

        old_item = root.takeAt(root.count() - 1)
        old_layout = old_item.layout()
        if old_layout is None:
            return

        known = {
            self.playlist.up_button,
            self.playlist.down_button,
            self.playlist.move_button,
            self.playlist.remove_button,
        }
        while old_layout.count():
            item = old_layout.takeAt(0)
            widget = item.widget()
            if widget is not None and widget not in known:
                widget.deleteLater()

        controls = QWidget(self.playlist)
        controls.setObjectName("playlistControlsCompact")
        controls.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        grid = QGridLayout(controls)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(4)

        self.playlist.move_button.setText("Pindah ke…")
        self.playlist.remove_button.setText("Hapus Playlist")
        grid.addWidget(self.playlist.up_button, 0, 0)
        grid.addWidget(self.playlist.down_button, 0, 1)
        grid.addWidget(self.playlist.move_button, 1, 0)
        grid.addWidget(self.playlist.remove_button, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        root.addWidget(controls)
        self.compact_playlist_controls = controls
