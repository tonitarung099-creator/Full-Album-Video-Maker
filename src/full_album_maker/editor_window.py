from __future__ import annotations

import threading
from uuid import uuid4

from PySide6.QtWidgets import QApplication, QMessageBox

from .ai_editor import (
    AIEditorAmbiguity,
    AIEditorEnvelope,
    AIEditorExecutor,
    EDITOR_SYSTEM,
    EDITOR_TOOLS,
    EditorAIContextBuilder,
    deterministic_action_id,
)
from .editor_commands import ReplaceDocument
from .editor_controller import RevisionConflict
from .editor_models import ProjectDocument
from .gemini_agent import GeminiAgent
from .legacy_sync_v2 import sync_legacy_media
from .style import APP_STYLE
from .template_system import template_choices
from .ui import MainWindow as LegacyMainWindow
from .v13_workspace import V13EditorWorkspace


class EditorMainWindow(LegacyMainWindow):
    """Main application shell with Editor V2, AI intents, Free Timeline and Song Visuals."""

    def __init__(self) -> None:
        self._editor_workspace_ready = False
        self._legacy_project_identity = None
        self._ai_editor_executor: AIEditorExecutor | None = None
        self._ai_pending: dict[str, tuple[str, int, str]] = {}
        self._ai_context_builder = EditorAIContextBuilder()
        super().__init__()
        self.setMinimumSize(1080, 680)
        self.resize(1500, 860)

        seed = ProjectDocument.new_empty("Editor Full Album")
        seed, _ = sync_legacy_media(seed, self.project)
        self.editor_workspace = V13EditorWorkspace(seed, self.splitter)
        self.editor_workspace.statusMessage.connect(self._on_editor_status)
        self.editor_workspace.dirtyChanged.connect(
            lambda _: self._update_editor_title()
        )

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
        self.chat.appendPlainText(
            "\n[EDITOR V2]\nGemini dapat mengedit layer, playlist, spectrum, cover, progress, dan template. "
            "Free Timeline menjaga gap/silence dan crossfade eksplisit. "
            "v1.3 menambahkan Visual Lagu per-song: foto/video, motion foto, serta transisi cut/fade/slide. "
            "Assignment Visual Lagu tetap lokal, berbasis song_id, tervalidasi, dan Undo/Redo.\n"
        )

    def _ensure_ai_executor(self) -> AIEditorExecutor:
        controller = self.editor_workspace.session.controller
        if (
            self._ai_editor_executor is None
            or self._ai_editor_executor.controller is not controller
        ):
            self._ai_editor_executor = AIEditorExecutor(
                controller,
                template_store=self.editor_workspace.custom_template_store,
            )
        return self._ai_editor_executor

    def _editor_template_ids(self) -> list[str]:
        values = [item.template_id for item in template_choices()]
        templates, _ = self.editor_workspace.custom_template_store.scan()
        values.extend(item.template_id for item in templates)
        return values

    def ask_agent(self):
        text = self.prompt.toPlainText().strip()
        if not text or self.agent_busy:
            return
        if not getattr(self, "_editor_workspace_ready", False):
            return super().ask_agent()

        self.agent_busy = True
        self.agent_send_btn.setEnabled(False)
        self.prompt.clear()
        self.chat.appendPlainText(f"\nANDA\n{text}\n")
        model = self.model.currentData() or "gemini-3.8-flash"
        snapshot = self.editor_workspace.session.snapshot()
        request_id = uuid4().hex
        self._ai_pending[request_id] = (
            snapshot.project_id,
            snapshot.revision,
            text,
        )
        while len(self._ai_pending) > 64:
            self._ai_pending.pop(next(iter(self._ai_pending)))

        context = self._ai_context_builder.build(
            snapshot,
            selected_layer_ids=self.editor_workspace.session.selected_layer_ids,
            user_text=text,
            template_ids=self._editor_template_ids(),
        )

        def work():
            try:
                if (
                    self.agent is None
                    or self.agent.model != model
                    or getattr(self.agent, "tools", None) != EDITOR_TOOLS
                ):
                    self.agent = GeminiAgent(
                        self.pool,
                        model=model,
                        tools=EDITOR_TOOLS,
                        system_prompt=EDITOR_SYSTEM,
                        history_limit=12,
                    )
                decision = self.agent.interpret(text, context)
                self.bridge.agent_decision.emit(decision, request_id)
            except Exception as exc:
                self.bridge.error.emit(str(exc))
                self.bridge.agent_done.emit()

        threading.Thread(target=work, daemon=True).start()

    def _handle_agent_decision(self, decision, request_id: str):
        try:
            self.chat.appendPlainText(f"\nGEMINI\n{decision.message}\n")
            pending = self._ai_pending.get(request_id)
            if pending is None:
                self.chat.appendPlainText(
                    "APP\nRespons AI tidak dikenali atau terlalu lama; tidak ada perubahan diterapkan.\n"
                )
                return
            project_id, expected_revision, original_text = pending
            if not decision.actions:
                return

            action_id = deterministic_action_id(
                project_id,
                expected_revision,
                request_id,
                decision.actions,
            )
            envelope = AIEditorEnvelope(
                action_id=action_id,
                project_id=project_id,
                expected_revision=expected_revision,
                actions=tuple(decision.actions),
            )
            executor = self._ensure_ai_executor()
            execution = executor.execute(envelope)

            if execution.project_changed:
                self.editor_workspace._after_edit()
            if execution.saved_template_id:
                self.editor_workspace._reload_template_catalog_s08(
                    select_id=execution.saved_template_id
                )
            if execution.summary_text:
                self.chat.appendPlainText(f"APP\n{execution.summary_text}\n")
            if execution.render_requested:
                self.chat.appendPlainText(
                    "APP\nDesain sudah di-commit. Membuka dialog render karena Anda meminta render eksplisit.\n"
                )
                self.editor_workspace.render_project()
        except AIEditorAmbiguity as exc:
            lines = [f"• {item}" for item in exc.candidates]
            self.chat.appendPlainText(
                "APP\n"
                + str(exc)
                + "\n"
                + "\n".join(lines)
                + "\nTidak ada perubahan diterapkan. Sebutkan kandidat yang dipilih lalu kirim ulang.\n"
            )
            try:
                self.prompt.setPlainText(original_text)
            except Exception:
                pass
        except RevisionConflict as exc:
            self.chat.appendPlainText(
                f"APP\nPerintah tidak diterapkan karena state editor sudah berubah ({exc}). "
                "Kirim ulang pada kondisi terbaru.\n"
            )
        except Exception as exc:
            self._error(f"Perintah Gemini Editor V2 gagal diterapkan:\n\n{exc}")
        finally:
            self._agent_done()

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
                self._ai_editor_executor = None
                self._legacy_project_identity = identity
                self._on_editor_status(
                    "Proyek legacy baru dimuat ke editor v2 tanpa menimpa file sumber."
                )
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
        title = self.windowTitle().replace(" • Editor V2 *", "").replace(
            " • Editor V2", ""
        )
        suffix = (
            " • Editor V2 *"
            if self.editor_workspace.session.is_dirty
            else " • Editor V2"
        )
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
                if (
                    answer == QMessageBox.StandardButton.Save
                    and not self.editor_workspace.save_project()
                ):
                    event.ignore()
                    return
        super().closeEvent(event)


def run() -> int:
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(APP_STYLE)
    window = EditorMainWindow()
    window.show()
    return app.exec()
