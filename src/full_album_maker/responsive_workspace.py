from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QSizePolicy, QWidget

from .editor_commands import SetLayerProperty
from .editor_models import ProjectDocument
from .editor_workspace import EditorWorkspace
from .spectrum_feature import apply_spectrum_preset


class ResponsiveEditorWorkspace(EditorWorkspace):
    """EditorWorkspace with compact controls for laptop layouts.

    S06 extends the S05 editor with cover/vinyl/playlist/progress controls while
    keeping the same project state and command stack.
    """

    def __init__(self, document: ProjectDocument | None = None, parent=None) -> None:
        super().__init__(document, parent)
        self._install_s05_actions()
        self._install_s06_actions()
        self._rebuild_compact_toolbar()
        self._rebuild_compact_playlist_controls()

    def _install_s05_actions(self) -> None:
        self.add_spectrum_btn = QPushButton("+ Spectrum", self)
        self.add_dynamic_title_btn = QPushButton("+ Judul Lagu", self)
        self.add_spectrum_btn.clicked.connect(self._add_spectrum_s05)
        self.add_dynamic_title_btn.clicked.connect(self._add_dynamic_title_s05)
        self.inspector.spectrumPresetRequested.connect(self._apply_spectrum_preset_s05)

    def _install_s06_actions(self) -> None:
        self.add_cover_btn = QPushButton("+ Cover", self)
        self.add_vinyl_btn = QPushButton("+ Vinyl", self)
        self.add_playlist_visual_btn = QPushButton("+ Playlist", self)
        self.add_progress_btn = QPushButton("+ Progress", self)
        self.add_cover_btn.clicked.connect(self._add_cover_s06)
        self.add_vinyl_btn.clicked.connect(self._add_vinyl_s06)
        self.add_playlist_visual_btn.clicked.connect(self._add_playlist_visual_s06)
        self.add_progress_btn.clicked.connect(self._add_progress_s06)

    def _add_spectrum_s05(self) -> None:
        try:
            self.session.add_spectrum_layer("neon_bars")
            self._after_edit()
            self._set_status("Spectrum audio nyata ditambahkan. Preview Akurat memakai compiler final yang sama.")
        except Exception as exc:
            self._set_status(f"Tambah spectrum gagal: {exc}")

    def _add_dynamic_title_s05(self) -> None:
        try:
            self.session.add_dynamic_title_layer()
            self._after_edit()
            self._set_status("Judul lagu dinamis ditambahkan dan mengikuti metadata playlist aktif.")
        except Exception as exc:
            self._set_status(f"Tambah judul dinamis gagal: {exc}")

    def _add_cover_s06(self) -> None:
        try:
            self.session.add_song_cover_layer()
            self._after_edit()
            self._set_status("Cover dinamis ditambahkan. Cover per lagu diprioritaskan, image pertama menjadi fallback.")
        except Exception as exc:
            self._set_status(f"Tambah cover gagal: {exc}")

    def _add_vinyl_s06(self) -> None:
        try:
            self.session.add_vinyl_layer()
            self._after_edit()
            self._set_status("Vinyl/disc prosedural ditambahkan dan akan berputar saat render.")
        except Exception as exc:
            self._set_status(f"Tambah vinyl gagal: {exc}")

    def _add_playlist_visual_s06(self) -> None:
        try:
            self.session.add_playlist_visual_layer()
            self._after_edit()
            self._set_status("Playlist visual ditambahkan. Halaman dan highlight mengikuti lagu aktif.")
        except Exception as exc:
            self._set_status(f"Tambah playlist visual gagal: {exc}")

    def _add_progress_s06(self) -> None:
        try:
            self.session.add_progress_visuals()
            self._after_edit()
            self._set_status("Progress + durasi lagu ditambahkan sebagai satu transaksi undo.")
        except Exception as exc:
            self._set_status(f"Tambah progress gagal: {exc}")

    def _apply_spectrum_preset_s05(self, layer_id: str, preset_id: str) -> None:
        try:
            layer = self.session.snapshot().layer_map().get(layer_id)
            if layer is None or layer.type != "spectrum":
                raise ValueError("Layer spectrum tidak ditemukan.")
            properties = apply_spectrum_preset(layer.properties, preset_id)
            commands = [SetLayerProperty(layer_id, key, value) for key, value in properties.items()]
            self.session.controller.dispatch(commands)
            self._after_edit()
            self._set_status(f"Preset spectrum diterapkan: {preset_id}.")
        except Exception as exc:
            self._set_status(f"Preset spectrum gagal: {exc}")

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
            self.add_spectrum_btn,
            self.add_dynamic_title_btn,
            self.add_cover_btn,
            self.add_vinyl_btn,
            self.add_playlist_visual_btn,
            self.add_progress_btn,
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
            [self.add_text_btn, self.add_dynamic_title_btn, self.add_spectrum_btn, self.duplicate_btn],
            [self.add_cover_btn, self.add_vinyl_btn, self.add_playlist_visual_btn, self.add_progress_btn],
            [self.delete_btn, self.use_all_btn, self.auto_btn, self.play_btn],
            [self.preview_btn, self.render_btn, self.snap_check],
        ]

        self.use_all_btn.setText("Semua Lagu")
        self.preview_btn.setText("Preview Akurat")
        self.render_btn.setText("Render V2")

        for row, widgets in enumerate(rows):
            for column, widget in enumerate(widgets):
                grid.addWidget(widget, row, column)

        zoom_label = QLabel("Zoom", toolbar)
        grid.addWidget(zoom_label, 5, 0)
        grid.addWidget(self.zoom_slider, 5, 1, 1, 3)
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
