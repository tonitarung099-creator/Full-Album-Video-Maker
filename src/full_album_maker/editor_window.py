from __future__ import annotations

from PySide6.QtWidgets import QApplication, QMessageBox

from .editor_commands import ReplaceDocument
from .editor_models import ProjectDocument
from .editor_workspace import EditorWorkspace
from .legacy_sync_v2 import sync_legacy_media
from .style import APP_STYLE
from .ui import MainWindow as LegacyMainWindow


class EditorMainWindow(LegacyMainWindow):
    """Main application shell with the explicit editor-v2 workspace.

    The existing media panel and Gemini panel remain in place. The old center
    TimelinePlan view is hidden, not patched, so legacy services can be retired
    incrementally without runtime monkey patches for the new editor.
    """

    def __init__(self) -> None:
        self._editor_workspace_ready = False
        self._legacy_project_identity = None
        super().__init__()
        self.setMinimumSize(1080, 680)
        self.resize(1500, 860)

        seed = ProjectDocument.new_empty("Editor Full Album")
        seed, _ = sync_legacy_media(seed, self.project)
        self.editor_workspace = EditorWorkspace(seed, self.splitter)
        self.editor_workspace.statusMessage.connect(self._on_editor_status)
        self.editor_workspace.dirtyChanged.connect(lambda _: self._update_editor_title())

        self._legacy_center = self.splitter.widget(1)
        self._legacy_center.hide()
        self.splitter.insertWidget(1, self.editor_workspace)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setStretchFactor(3, 0)
        self.splitter.setSizes([315, 780, 0, 350])

        self._legacy_project_identity = id(self.project)
        self._editor_workspace_ready = True
        self._update_editor_title()

    def refresh(self, *args, **kwargs):
        result = super().refresh(*args, **kwargs)
        if not getattr(self, "_editor_workspace_ready", False):
            return result
        try:
            identity = id(self.project)
            if identity != self._legacy_project_identity:
                document = ProjectDocument.new_empty("Editor Full Album")
                document, _ = sync_legacy_media(document, self.project)
                self.editor_workspace.set_document(document)
                self._legacy_project_identity = identity
                self._on_editor_status("Proyek legacy baru dimuat ke editor v2 tanpa menimpa file sumber.")
            else:
                current = self.editor_workspace.document()
                merged, changed = sync_legacy_media(current, self.project)
                if changed:
                    self.editor_workspace.dispatch_external(
                        ReplaceDocument(merged),
                        message="Media panel disinkronkan ke library editor v2.",
                    )
        except Exception as exc:
            self._on_editor_status(f"Sinkron media v2 gagal: {exc}")
        self._update_editor_title()
        return result

    def _on_editor_status(self, message: str) -> None:
        if hasattr(self, "chat"):
            try:
                self.chat.appendPlainText(f"[EDITOR V2] {message}")
            except Exception:
                pass

    def _update_editor_title(self) -> None:
        title = self.windowTitle().replace(" • Editor V2 *", "").replace(" • Editor V2", "")
        suffix = " • Editor V2 *" if self.editor_workspace.session.is_dirty else " • Editor V2"
        self.setWindowTitle(title + suffix)

    def closeEvent(self, event) -> None:
        if getattr(self, "_editor_workspace_ready", False):
            if getattr(self.editor_workspace, "_render_busy", False):
                QMessageBox.information(
                    self,
                    "Render editor masih berjalan",
                    "Render Editor V2 masih berjalan. Selesaikan render sebelum menutup aplikasi.",
                )
                event.ignore()
                return
            if self.editor_workspace.session.is_dirty:
                answer = QMessageBox.question(
                    self,
                    "Perubahan Editor V2 belum disimpan",
                    "Simpan perubahan Editor V2 sebelum menutup aplikasi?",
                    QMessageBox.StandardButton.Save
                    | QMessageBox.StandardButton.Discard
                    | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Save,
                )
                if answer == QMessageBox.StandardButton.Cancel:
                    event.ignore()
                    return
                if answer == QMessageBox.StandardButton.Save and not self.editor_workspace.save_project():
                    event.ignore()
                    return
        super().closeEvent(event)


def run() -> int:
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(APP_STYLE)
    window = EditorMainWindow()
    window.show()
    return app.exec()
