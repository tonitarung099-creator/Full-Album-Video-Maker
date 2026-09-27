from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGridLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from .custom_template_builder import (
    CUSTOM_TEMPLATE_SUFFIX,
    CustomTemplateStore,
    SetCustomTemplateMarker,
    apply_builtin_template_commands,
    apply_custom_template_commands,
    current_custom_template_id,
    current_template_reference,
    is_custom_template_id,
)
from .editor_commands import SetLayerProperty
from .editor_models import ProjectDocument
from .editor_workspace import EditorWorkspace
from .spectrum_feature import apply_spectrum_preset
from .template_system import apply_template_command, template_choices


class ResponsiveEditorWorkspace(EditorWorkspace):
    """Compact editor workspace for laptop layouts.

    S08 extends the built-in S07 template selector with portable custom templates.
    Custom templates live under data/templates/custom in the portable app folder,
    can be exported/imported, and still resolve to normal editable project layers.
    """

    def __init__(
        self,
        document: ProjectDocument | None = None,
        parent=None,
        *,
        custom_template_root: str | Path | None = None,
    ) -> None:
        self.custom_template_store = CustomTemplateStore(custom_template_root)
        super().__init__(document, parent)
        self._install_s05_actions()
        self._install_s06_actions()
        self._install_s07_actions()
        self._install_s08_actions()
        self._reload_template_catalog_s08()
        self._rebuild_compact_toolbar()
        self._rebuild_compact_playlist_controls()
        self._sync_template_combo()

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

    def _install_s07_actions(self) -> None:
        self.template_combo = QComboBox(self)
        self.template_combo.setObjectName("templateComboS07")
        self.apply_template_btn = QPushButton("Terapkan Template", self)
        self.apply_template_btn.setObjectName("applyTemplateS07")
        self.apply_template_btn.clicked.connect(self._apply_template_s07)
        self.template_combo.currentIndexChanged.connect(self._template_changed_s07)

    def _install_s08_actions(self) -> None:
        self.save_custom_template_btn = QPushButton("Simpan", self)
        self.import_custom_template_btn = QPushButton("Impor", self)
        self.export_custom_template_btn = QPushButton("Ekspor", self)
        self.delete_custom_template_btn = QPushButton("Hapus", self)
        self.save_custom_template_btn.setToolTip("Simpan layout saat ini sebagai template kustom portable")
        self.import_custom_template_btn.setToolTip("Impor file template .famtpl.json")
        self.export_custom_template_btn.setToolTip("Ekspor template kustom yang dipilih")
        self.delete_custom_template_btn.setToolTip("Hapus template kustom dari folder portable")
        for button in (
            self.save_custom_template_btn,
            self.import_custom_template_btn,
            self.export_custom_template_btn,
            self.delete_custom_template_btn,
        ):
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.save_custom_template_btn.setObjectName("saveCustomTemplateS08")
        self.import_custom_template_btn.setObjectName("importCustomTemplateS08")
        self.export_custom_template_btn.setObjectName("exportCustomTemplateS08")
        self.delete_custom_template_btn.setObjectName("deleteCustomTemplateS08")
        self.save_custom_template_btn.clicked.connect(self._save_custom_template_s08)
        self.import_custom_template_btn.clicked.connect(self._import_custom_template_s08)
        self.export_custom_template_btn.clicked.connect(self._export_custom_template_s08)
        self.delete_custom_template_btn.clicked.connect(self._delete_custom_template_s08)

    def _reload_template_catalog_s08(self, *, select_id: str = "") -> None:
        if not hasattr(self, "template_combo"):
            return
        previous = select_id or str(self.template_combo.currentData() or "")
        templates, errors = self.custom_template_store.scan()
        self.template_combo.blockSignals(True)
        try:
            self.template_combo.clear()
            for definition in template_choices():
                self.template_combo.addItem(definition.label, definition.template_id)
                index = self.template_combo.count() - 1
                self.template_combo.setItemData(index, definition.description, role=3)
            if templates:
                self.template_combo.insertSeparator(self.template_combo.count())
                for template in templates:
                    self.template_combo.addItem(f"Kustom • {template.label}", template.template_id)
                    index = self.template_combo.count() - 1
                    self.template_combo.setItemData(index, template.description, role=3)
            index = self.template_combo.findData(previous)
            if index < 0:
                index = 0 if self.template_combo.count() else -1
            self.template_combo.setCurrentIndex(index)
        finally:
            self.template_combo.blockSignals(False)
        self._template_changed_s07(self.template_combo.currentIndex())
        if errors:
            self._set_status(
                f"{len(errors)} file template kustom rusak diabaikan. File valid tetap dimuat."
            )

    def _template_changed_s07(self, index: int) -> None:
        if not hasattr(self, "template_combo") or index < 0:
            return
        description = self.template_combo.itemData(index, role=3)
        self.template_combo.setToolTip(str(description or ""))
        template_id = str(self.template_combo.currentData() or "")
        is_custom = is_custom_template_id(template_id)
        if hasattr(self, "export_custom_template_btn"):
            self.export_custom_template_btn.setEnabled(is_custom)
            self.delete_custom_template_btn.setEnabled(is_custom)

    def _sync_template_combo(self) -> None:
        if not hasattr(self, "template_combo"):
            return
        template_id = current_template_reference(self.session.snapshot())
        if not template_id:
            return
        index = self.template_combo.findData(template_id)
        if index >= 0 and index != self.template_combo.currentIndex():
            self.template_combo.blockSignals(True)
            self.template_combo.setCurrentIndex(index)
            self.template_combo.blockSignals(False)
            self._template_changed_s07(index)

    def _refresh_all(self) -> None:
        super()._refresh_all()
        self._sync_template_combo()

    def _apply_template_s07(self) -> None:
        try:
            template_id = str(self.template_combo.currentData() or "")
            if not template_id:
                raise ValueError("Pilih template terlebih dahulu.")
            snapshot = self.session.snapshot()
            if is_custom_template_id(template_id):
                template = self.custom_template_store.load(template_id)
                commands = apply_custom_template_commands(snapshot, template)
                label = template.label
            else:
                command = apply_template_command(snapshot, template_id)
                commands = apply_builtin_template_commands(snapshot, command)
                label = self.template_combo.currentText()
            self.session.controller.dispatch(commands)
            doc = self.session.snapshot()
            first = next((layer.layer_id for layer in doc.layers if layer.origin == "template"), None)
            self.session.select_one(first)
            self._after_edit()
            self._set_status(
                f"Template {label} diterapkan sebagai layer editable. Layer manual lain tetap dipertahankan."
            )
        except Exception as exc:
            self._set_status(f"Terapkan template gagal: {exc}")

    def _save_custom_template_s08(self) -> None:
        name, accepted = QInputDialog.getText(
            self,
            "Simpan Template Kustom",
            "Nama template:",
            text="Template Kustom",
        )
        if not accepted:
            return
        description, accepted = QInputDialog.getMultiLineText(
            self,
            "Deskripsi Template",
            "Deskripsi singkat (opsional):",
            "",
        )
        if not accepted:
            return
        try:
            template = self.custom_template_store.create_from_document(
                self.session.snapshot(), name, description
            )
            self._reload_template_catalog_s08(select_id=template.template_id)
            self._set_status(
                f"Template kustom '{template.label}' disimpan portabel dengan {len(template.layers)} layer."
            )
        except Exception as exc:
            self._set_status(f"Simpan template kustom gagal: {exc}")

    def _import_custom_template_s08(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Impor Template Full Album",
            "",
            "Full Album Template (*.famtpl.json);;JSON (*.json)",
        )
        if not path:
            return
        try:
            template = self.custom_template_store.import_template(path)
            self._reload_template_catalog_s08(select_id=template.template_id)
            self._set_status(f"Template kustom diimpor: {template.label}")
        except Exception as exc:
            self._set_status(f"Impor template gagal: {exc}")

    def _export_custom_template_s08(self) -> None:
        template_id = str(self.template_combo.currentData() or "")
        if not is_custom_template_id(template_id):
            self._set_status("Ekspor langsung hanya untuk template kustom. Simpan layout sebagai kustom dulu.")
            return
        try:
            template = self.custom_template_store.load(template_id)
        except Exception as exc:
            self._set_status(f"Template kustom tidak dapat dibaca: {exc}")
            return
        safe_name = "_".join(template.label.split()) or "Template_Kustom"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Ekspor Template Full Album",
            f"{safe_name}{CUSTOM_TEMPLATE_SUFFIX}",
            "Full Album Template (*.famtpl.json)",
        )
        if not path:
            return
        try:
            saved = self.custom_template_store.export_template(template_id, path)
            self._set_status(f"Template diekspor: {saved.name}")
        except Exception as exc:
            self._set_status(f"Ekspor template gagal: {exc}")

    def _delete_custom_template_s08(self) -> None:
        template_id = str(self.template_combo.currentData() or "")
        if not is_custom_template_id(template_id):
            return
        try:
            template = self.custom_template_store.load(template_id)
        except Exception as exc:
            self._set_status(f"Template kustom tidak dapat dibaca: {exc}")
            return
        answer = QMessageBox.question(
            self,
            "Hapus Template Kustom",
            f"Hapus template '{template.label}' dari folder portable?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.custom_template_store.delete(template_id)
            if current_custom_template_id(self.session.snapshot()) == template_id:
                self.session.controller.dispatch(SetCustomTemplateMarker(""))
                self._after_edit()
            self._reload_template_catalog_s08()
            self._set_status(f"Template kustom dihapus: {template.label}")
        except Exception as exc:
            self._set_status(f"Hapus template gagal: {exc}")

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
            self.template_combo,
            self.apply_template_btn,
            self.save_custom_template_btn,
            self.import_custom_template_btn,
            self.export_custom_template_btn,
            self.delete_custom_template_btn,
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

        template_label = QLabel("Template", toolbar)
        grid.addWidget(template_label, 0, 0)
        grid.addWidget(self.template_combo, 0, 1, 1, 2)
        grid.addWidget(self.apply_template_btn, 0, 3)

        rows = [
            [self.save_custom_template_btn, self.import_custom_template_btn, self.export_custom_template_btn, self.delete_custom_template_btn],
            [self.open_btn, self.save_btn, self.undo_btn, self.redo_btn],
            [self.add_text_btn, self.add_dynamic_title_btn, self.add_spectrum_btn, self.duplicate_btn],
            [self.add_cover_btn, self.add_vinyl_btn, self.add_playlist_visual_btn, self.add_progress_btn],
            [self.delete_btn, self.use_all_btn, self.auto_btn, self.play_btn],
            [self.preview_btn, self.render_btn, self.snap_check],
        ]

        self.use_all_btn.setText("Semua Lagu")
        self.preview_btn.setText("Preview Akurat")
        self.render_btn.setText("Render V2")

        for row, widgets in enumerate(rows, start=1):
            for column, widget in enumerate(widgets):
                grid.addWidget(widget, row, column)

        zoom_label = QLabel("Zoom", toolbar)
        grid.addWidget(zoom_label, 7, 0)
        grid.addWidget(self.zoom_slider, 7, 1, 1, 3)
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
