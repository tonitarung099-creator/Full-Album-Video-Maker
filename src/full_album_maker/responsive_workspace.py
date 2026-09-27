from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QLabel, QSizePolicy, QWidget

from .editor_models import ProjectDocument
from .editor_workspace import EditorWorkspace


class ResponsiveEditorWorkspace(EditorWorkspace):
    """EditorWorkspace with a compact multi-row toolbar for laptop layouts.

    The base workspace owns all actions/signals. This class only changes their
    presentation so the center editor can coexist with Media + AI panels on a
    1366px desktop without clipping or overlap.
    """

    def __init__(self, document: ProjectDocument | None = None, parent=None) -> None:
        super().__init__(document, parent)
        self._rebuild_compact_toolbar()

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

        first_row = [
            self.open_btn,
            self.save_btn,
            self.undo_btn,
            self.redo_btn,
            self.add_text_btn,
            self.duplicate_btn,
            self.delete_btn,
        ]
        second_row = [
            self.use_all_btn,
            self.auto_btn,
            self.play_btn,
            self.preview_btn,
            self.render_btn,
            self.snap_check,
        ]

        # Shorter labels keep the actions clear while avoiding a 1500+ px
        # minimum-width toolbar on Windows font metrics.
        self.use_all_btn.setText("Semua Lagu")
        self.preview_btn.setText("Preview Akurat")
        self.render_btn.setText("Render V2")

        for column, widget in enumerate(first_row):
            grid.addWidget(widget, 0, column)
        for column, widget in enumerate(second_row):
            grid.addWidget(widget, 1, column)

        zoom_label = QLabel("Zoom", toolbar)
        grid.addWidget(zoom_label, 2, 0)
        grid.addWidget(self.zoom_slider, 2, 1, 1, 4)
        grid.setColumnStretch(4, 1)

        root.insertWidget(0, toolbar)
        self.compact_toolbar = toolbar
