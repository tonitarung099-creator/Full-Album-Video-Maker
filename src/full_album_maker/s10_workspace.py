from __future__ import annotations

import hashlib
from pathlib import Path
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .custom_template_builder import is_custom_template_id
from .editor_models import ProjectDocument
from .paths import temp_dir
from .responsive_workspace import ResponsiveEditorWorkspace
from .template_system import template_definition
from .template_thumbnail import render_template_thumbnail


class _TemplatePreviewBridge(QObject):
    ready = Signal(int, str, str)
    failed = Signal(int, str, str)


class S10EditorWorkspace(ResponsiveEditorWorkspace):
    """Responsive workspace with a real-render preview card for built-in templates.

    The card is intentionally small so the laptop layout remains usable. It never
    substitutes a stock illustration: the selected built-in template is applied to
    a private document clone and rendered through FFmpegV2Compiler.compile_frame().
    Rendering is asynchronous, cached by project content + template ID, and stale
    results are ignored when the user changes selection.
    """

    def __init__(
        self,
        document: ProjectDocument | None = None,
        parent=None,
        *,
        custom_template_root: str | Path | None = None,
        template_preview_enabled: bool = True,
    ) -> None:
        self._s10_preview_serial = 0
        self._s10_preview_enabled = bool(template_preview_enabled)
        super().__init__(
            document,
            parent,
            custom_template_root=custom_template_root,
        )
        self._s10_preview_bridge = _TemplatePreviewBridge(self)
        self._s10_preview_bridge.ready.connect(self._template_preview_ready_s10)
        self._s10_preview_bridge.failed.connect(self._template_preview_failed_s10)
        self._install_template_preview_card_s10()
        self.template_combo.currentIndexChanged.connect(
            self._template_selection_changed_s10
        )
        self._schedule_template_preview_s10()

    def _install_template_preview_card_s10(self) -> None:
        card = QFrame(self)
        card.setObjectName("templatePreviewCardS10")
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setMaximumHeight(116)

        row = QHBoxLayout(card)
        row.setContentsMargins(8, 7, 8, 7)
        row.setSpacing(9)

        self.template_preview_image_s10 = QLabel("Preview\nTemplate", card)
        self.template_preview_image_s10.setObjectName("templatePreviewImageS10")
        self.template_preview_image_s10.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.template_preview_image_s10.setFixedSize(160, 90)
        self.template_preview_image_s10.setStyleSheet(
            "QLabel { background: #0d1117; border: 1px solid #30363d; color: #8b949e; }"
        )
        row.addWidget(self.template_preview_image_s10, 0)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)
        self.template_preview_title_s10 = QLabel("Template", card)
        self.template_preview_title_s10.setObjectName("templatePreviewTitleS10")
        self.template_preview_description_s10 = QLabel("", card)
        self.template_preview_description_s10.setObjectName("muted")
        self.template_preview_description_s10.setWordWrap(True)
        self.template_preview_status_s10 = QLabel("Preview aktual belum dibuat.", card)
        self.template_preview_status_s10.setObjectName("muted")
        self.template_preview_status_s10.setWordWrap(True)
        self.template_preview_refresh_s10 = QPushButton("Refresh Preview", card)
        self.template_preview_refresh_s10.setObjectName("templatePreviewRefreshS10")
        self.template_preview_refresh_s10.setMaximumWidth(132)
        self.template_preview_refresh_s10.clicked.connect(
            lambda: self._schedule_template_preview_s10(force=True)
        )
        text_col.addWidget(self.template_preview_title_s10)
        text_col.addWidget(self.template_preview_description_s10, 1)
        text_col.addWidget(self.template_preview_status_s10)
        text_col.addWidget(self.template_preview_refresh_s10, 0)
        row.addLayout(text_col, 1)

        root = self.layout()
        if root is not None:
            root.insertWidget(1, card)
        self.template_preview_card_s10 = card

    def _template_selection_changed_s10(self, _index: int) -> None:
        self._schedule_template_preview_s10()

    def _preview_cache_path_s10(
        self,
        document: ProjectDocument,
        template_id: str,
    ) -> Path:
        signature = repr(document.content_signature())
        digest = hashlib.sha256(
            f"{document.project_id}|{signature}|{template_id}".encode("utf-8")
        ).hexdigest()[:20]
        safe_id = "".join(
            character if character.isalnum() or character in "-_" else "_"
            for character in template_id
        )
        root = temp_dir() / "template-previews"
        root.mkdir(parents=True, exist_ok=True)
        return root / f"{safe_id}-{digest}.png"

    def _schedule_template_preview_s10(self, *, force: bool = False) -> None:
        if not hasattr(self, "template_preview_image_s10"):
            return
        template_id = str(self.template_combo.currentData() or "")
        label = self.template_combo.currentText().strip() or "Template"
        description = str(
            self.template_combo.itemData(self.template_combo.currentIndex(), role=3)
            or ""
        )
        self.template_preview_title_s10.setText(label)
        self.template_preview_description_s10.setText(description)

        self._s10_preview_serial += 1
        serial = self._s10_preview_serial

        if not template_id:
            self.template_preview_image_s10.clear()
            self.template_preview_image_s10.setText("Pilih\nTemplate")
            self.template_preview_status_s10.setText("Tidak ada template terpilih.")
            return
        if is_custom_template_id(template_id):
            self.template_preview_image_s10.clear()
            self.template_preview_image_s10.setText("Template\nKustom")
            self.template_preview_status_s10.setText(
                "Template kustom tetap editable. Gunakan Preview Akurat setelah diterapkan."
            )
            return
        try:
            definition = template_definition(template_id)
        except Exception as exc:
            self.template_preview_status_s10.setText(f"Template tidak valid: {exc}")
            return
        self.template_preview_title_s10.setText(definition.label)
        self.template_preview_description_s10.setText(definition.description)

        if not self._s10_preview_enabled:
            self.template_preview_status_s10.setText(
                "Preview aktual dinonaktifkan pada sesi ini."
            )
            return

        snapshot = self.session.snapshot()
        if not any(song.enabled for song in snapshot.playlist.entries):
            self.template_preview_image_s10.clear()
            self.template_preview_image_s10.setText("Belum ada\nlagu")
            self.template_preview_status_s10.setText(
                "Tambahkan minimal satu lagu untuk membuat preview aktual."
            )
            return

        destination = self._preview_cache_path_s10(snapshot, template_id)
        if force:
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
        if destination.exists() and destination.stat().st_size > 0:
            self._template_preview_ready_s10(
                serial,
                template_id,
                str(destination),
            )
            return

        self.template_preview_image_s10.clear()
        self.template_preview_image_s10.setText("Rendering…")
        self.template_preview_status_s10.setText(
            "Membuat thumbnail dari render aktual…"
        )
        self.template_preview_refresh_s10.setEnabled(False)

        def work() -> None:
            try:
                path = render_template_thumbnail(
                    snapshot,
                    template_id,
                    destination,
                )
                self._s10_preview_bridge.ready.emit(
                    serial,
                    template_id,
                    path,
                )
            except Exception as exc:
                self._s10_preview_bridge.failed.emit(
                    serial,
                    template_id,
                    str(exc),
                )

        threading.Thread(
            target=work,
            daemon=True,
            name=f"template-preview-{template_id}",
        ).start()

    def _template_preview_ready_s10(
        self,
        serial: int,
        template_id: str,
        path: str,
    ) -> None:
        if serial != self._s10_preview_serial:
            return
        if template_id != str(self.template_combo.currentData() or ""):
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self._template_preview_failed_s10(
                serial,
                template_id,
                "PNG preview tidak dapat dibaca.",
            )
            return
        scaled = pixmap.scaled(
            self.template_preview_image_s10.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.template_preview_image_s10.setText("")
        self.template_preview_image_s10.setPixmap(scaled)
        self.template_preview_status_s10.setText(
            "Thumbnail ini berasal dari render aktual template."
        )
        self.template_preview_refresh_s10.setEnabled(True)

    def _template_preview_failed_s10(
        self,
        serial: int,
        template_id: str,
        message: str,
    ) -> None:
        if serial != self._s10_preview_serial:
            return
        if template_id != str(self.template_combo.currentData() or ""):
            return
        self.template_preview_image_s10.clear()
        self.template_preview_image_s10.setText("Preview\ngagal")
        self.template_preview_status_s10.setText(
            f"Preview aktual gagal: {message}"
        )
        self.template_preview_refresh_s10.setEnabled(True)
