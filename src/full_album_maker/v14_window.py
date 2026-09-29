from __future__ import annotations

import threading
from uuid import uuid4

from PySide6.QtWidgets import QApplication

from .ai_editor_v14 import (
    V14AIEditorExecutor,
    V14_EDITOR_SYSTEM,
    V14_EDITOR_TOOLS,
    V14EditorAIContextBuilder,
)
from .editor_window import EditorMainWindow
from .gemini_agent import GeminiAgent
from .style import APP_STYLE


class V14EditorMainWindow(EditorMainWindow):
    """Editor window whose Gemini surface has parity with v1.1-v1.3 features."""

    def __init__(self) -> None:
        super().__init__()
        self._ai_editor_executor = None
        self._ai_context_builder = V14EditorAIContextBuilder()
        self.chat.appendPlainText(
            "[AI v1.4] Gemini sekarang dapat mengatur Cover, Visual Lagu, Circular Spectrum, "
            "serta Free Timeline/crossfade. Semua assignment tetap stable-ID, fail-closed, "
            "dan satu respons edit tetap satu transaksi Undo."
        )

    def _ensure_ai_executor(self) -> V14AIEditorExecutor:
        controller = self.editor_workspace.session.controller
        if (
            self._ai_editor_executor is None
            or self._ai_editor_executor.controller is not controller
            or not isinstance(self._ai_editor_executor, V14AIEditorExecutor)
        ):
            self._ai_editor_executor = V14AIEditorExecutor(
                controller,
                template_store=self.editor_workspace.custom_template_store,
            )
        return self._ai_editor_executor

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
                    or getattr(self.agent, "tools", None) != V14_EDITOR_TOOLS
                ):
                    self.agent = GeminiAgent(
                        self.pool,
                        model=model,
                        tools=V14_EDITOR_TOOLS,
                        system_prompt=V14_EDITOR_SYSTEM,
                        history_limit=12,
                    )
                decision = self.agent.interpret(text, context)
                self.bridge.agent_decision.emit(decision, request_id)
            except Exception as exc:
                self.bridge.error.emit(str(exc))
                self.bridge.agent_done.emit()

        threading.Thread(target=work, daemon=True).start()


def run() -> int:
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(APP_STYLE)
    window = V14EditorMainWindow()
    window.show()
    return app.exec()
