from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QScrollArea,
)

from . import ui as ui_module
from .gemini_agent import GeminiAgent
from .timeline import project_signature

_installed = False
_originals: dict[str, Any] = {}


def _append_render_log_ui(window) -> None:
    if not hasattr(window, "log") or not hasattr(window, "splitter"):
        return
    center = window.splitter.widget(1)
    if center is None or center.layout() is None:
        return
    window.log.setReadOnly(True)
    window.log.setVisible(True)
    window.log.setMaximumHeight(120)
    window.log.document().setMaximumBlockCount(300)
    title = QLabel("▤  Log Render — maksimal 300 baris")
    title.setObjectName("sectionTitle")
    center.layout().addWidget(title)
    center.layout().addWidget(window.log)


def _add_remove_media_buttons(window) -> None:
    media = window.splitter.widget(0) if hasattr(window, "splitter") else None
    if media is None or media.layout() is None:
        return

    # Base media panel keeps video card at index 1 and audio card at index 2.
    # The visual feature appends photo controls after those cards, so the
    # positions remain stable while preserving the existing layout.
    for card_index, text, callback_name in (
        (1, "Hapus Video", "remove_video_selected"),
        (2, "Hapus Lagu", "remove_audio_selected"),
    ):
        item = media.layout().itemAt(card_index)
        card = item.widget() if item is not None else None
        if card is None or card.layout() is None:
            continue
        controls_item = card.layout().itemAt(2)
        controls = controls_item.layout() if controls_item is not None else None
        if controls is None:
            continue
        button = QPushButton(text)
        button.setToolTip("Menghapus dari proyek saja. File sumber di disk tidak dihapus.")
        button.clicked.connect(getattr(window, callback_name))
        controls.addWidget(button)


def _make_panels_scrollable(window) -> None:
    splitter = getattr(window, "splitter", None)
    if splitter is None:
        return
    for index in range(splitter.count()):
        current = splitter.widget(index)
        if current is None or isinstance(current, QScrollArea):
            continue
        scroll = QScrollArea()
        scroll.setObjectName(f"panelScroll{index}")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        old = splitter.replaceWidget(index, scroll)
        if old is not None:
            scroll.setWidget(old)


def _configure_preset_combo(window) -> None:
    preset = getattr(window, "preset", None)
    if preset is None:
        return
    if preset.findData("__custom__") < 0:
        preset.addItem("Kustom", "__custom__")
    try:
        preset.currentIndexChanged.disconnect(window.apply_preset)
    except (RuntimeError, TypeError):
        pass
    try:
        preset.activated.disconnect(window.apply_preset)
    except (RuntimeError, TypeError):
        pass
    preset.activated.connect(window.apply_preset)


def _patched_init(self, *args, **kwargs) -> None:
    _originals["init"](self, *args, **kwargs)
    self._agent_epoch = 0
    self.setMinimumSize(1080, 620)

    _append_render_log_ui(self)
    _add_remove_media_buttons(self)
    _configure_preset_combo(self)
    _make_panels_scrollable(self)

    if hasattr(self, "model"):
        self.model.currentIndexChanged.connect(self._invalidate_agent_context)

    load_error = getattr(self.pool, "last_load_error", "")
    if load_error:
        self.chat.appendPlainText(
            "\nAPP\n⚠ Vault Gemini lama tidak dapat dibuka. "
            "Aplikasi tidak menimpa file lama; salinan korup telah dikarantina bila memungkinkan.\n"
        )
    self.refresh()


def _preset_matches(settings, data: Any) -> bool:
    if not data or data == "__custom__":
        return False
    try:
        resolution, fps, video_bitrate, codec = data
    except (TypeError, ValueError):
        return False
    return (
        tuple(resolution) == (settings.width, settings.height)
        and int(fps) == int(settings.fps)
        and str(video_bitrate) == str(settings.video_bitrate)
        and str(codec) == str(settings.codec)
        and str(settings.audio_bitrate) == "320k"
    )


def _patched_apply_preset(self, *_args) -> None:
    data = self.preset.currentData()
    if not data or data == "__custom__":
        return
    try:
        resolution, fps, bitrate, codec = data
    except (TypeError, ValueError) as exc:
        raise ValueError("Data preset output tidak valid.") from exc
    s = self.project.settings
    s.width, s.height = int(resolution[0]), int(resolution[1])
    s.fps = int(fps)
    s.video_bitrate = str(bitrate)
    s.audio_bitrate = "320k"
    s.codec = str(codec)
    self.invalidate_timeline()
    self.refresh()


def _patched_sync_controls(self) -> None:
    _originals["sync_controls"](self)
    preset = getattr(self, "preset", None)
    if preset is None:
        return
    preset.blockSignals(True)
    try:
        matched = -1
        for index in range(preset.count()):
            if _preset_matches(self.project.settings, preset.itemData(index)):
                matched = index
                break
        if matched < 0:
            matched = preset.findData("__custom__")
        if matched >= 0:
            preset.setCurrentIndex(matched)
    finally:
        preset.blockSignals(False)


def _remove_from_visual_order(project, path: str) -> None:
    order = getattr(project, "_visual_order", None)
    if not isinstance(order, list):
        return
    target = str(Path(path).expanduser().resolve()).casefold()
    kept = []
    for value in order:
        try:
            key = str(Path(value).expanduser().resolve()).casefold()
        except Exception:
            key = str(value).casefold()
        if key != target:
            kept.append(value)
    setattr(project, "_visual_order", kept)


def _remove_video_selected(self) -> None:
    row = self.video_list.currentRow()
    if row < 0 or row >= len(self.project.videos):
        return
    path = self.project.videos[row].path
    try:
        self.controller.execute("remove_video", {"position": row + 1})
        _remove_from_visual_order(self.project, path)
        self.invalidate_timeline()
        self.refresh()
        if self.project.videos:
            self.video_list.setCurrentRow(min(row, len(self.project.videos) - 1))
    except Exception as exc:
        self._error(f"Gagal menghapus video dari proyek:\n\n{exc}")


def _remove_audio_selected(self) -> None:
    row = self.audio_list.currentRow()
    if row < 0 or row >= len(self.project.audios):
        return
    try:
        self.controller.execute("remove_audio", {"position": row + 1})
        self.invalidate_timeline()
        self.refresh()
        if self.project.audios:
            self.audio_list.setCurrentRow(min(row, len(self.project.audios) - 1))
    except Exception as exc:
        self._error(f"Gagal menghapus lagu dari proyek:\n\n{exc}")


def _invalidate_agent_context(self, *_args) -> None:
    self._agent_epoch = int(getattr(self, "_agent_epoch", 0)) + 1
    self.agent = None


def _patched_ask_agent(self) -> None:
    text = self.prompt.toPlainText().strip()
    if not text or self.agent_busy:
        return

    self.agent_busy = True
    self.agent_send_btn.setEnabled(False)
    self.prompt.clear()
    self.chat.appendPlainText(f"\nANDA\n{text}\n")
    model = self.model.currentData() or "gemini-3.8-flash"
    context = self.controller.summary()
    context_signature = project_signature(self.project)
    request_epoch = int(getattr(self, "_agent_epoch", 0))

    def work():
        try:
            if self.agent is None or self.agent.model != model:
                self.agent = GeminiAgent(self.pool, model=model)
            agent = self.agent
            decision = agent.interpret(text, context)
            setattr(decision, "_ui_epoch", request_epoch)
            self.bridge.agent_decision.emit(decision, context_signature)
        except Exception as exc:
            if request_epoch == int(getattr(self, "_agent_epoch", 0)):
                self.bridge.error.emit(str(exc))
            self.bridge.agent_done.emit()

    threading.Thread(target=work, daemon=True).start()


def _patched_handle_agent_decision(self, decision, context_signature: str) -> None:
    decision_epoch = int(
        getattr(decision, "_ui_epoch", getattr(self, "_agent_epoch", 0))
    )
    if decision_epoch != int(getattr(self, "_agent_epoch", 0)):
        self.chat.appendPlainText(
            "\nAPP\nRespons Gemini lama diabaikan karena chat/proyek/model sudah berubah.\n"
        )
        self._agent_done()
        return
    _originals["handle_agent_decision"](self, decision, context_signature)


def _patched_reset_agent_chat(self) -> None:
    was_busy = bool(self.agent_busy)
    self._invalidate_agent_context()
    self.chat.setPlainText(
        "✦ GEMINI\nHalo! Saya Gemini Agent.\n"
        "Cukup tulis perintah seperti “susun semua lagu dan video”.\n"
    )
    if was_busy:
        self.chat.appendPlainText(
            "APP\nRequest Gemini yang sedang berjalan tidak dapat dihentikan di jaringan, "
            "tetapi hasilnya sudah ditandai kedaluwarsa dan tidak akan diterapkan.\n"
        )


def _patched_load_project_file(self) -> None:
    previous_project = self.project
    _originals["load_project_file"](self)
    if self.project is not previous_project:
        self._invalidate_agent_context()


def install_ui_hardening() -> None:
    global _installed
    if _installed:
        return
    MainWindow = ui_module.MainWindow
    _originals.update(
        {
            "init": MainWindow.__init__,
            "apply_preset": MainWindow.apply_preset,
            "sync_controls": MainWindow._sync_controls_from_project,
            "ask_agent": MainWindow.ask_agent,
            "handle_agent_decision": MainWindow._handle_agent_decision,
            "reset_agent_chat": MainWindow.reset_agent_chat,
            "load_project_file": MainWindow.load_project_file,
        }
    )
    MainWindow.__init__ = _patched_init
    MainWindow.apply_preset = _patched_apply_preset
    MainWindow._sync_controls_from_project = _patched_sync_controls
    MainWindow.remove_video_selected = _remove_video_selected
    MainWindow.remove_audio_selected = _remove_audio_selected
    MainWindow._invalidate_agent_context = _invalidate_agent_context
    MainWindow.ask_agent = _patched_ask_agent
    MainWindow._handle_agent_decision = _patched_handle_agent_decision
    MainWindow.reset_agent_chat = _patched_reset_agent_chat
    MainWindow.load_project_file = _patched_load_project_file
    _installed = True


def uninstall_ui_hardening() -> None:
    global _installed
    if not _installed:
        return
    MainWindow = ui_module.MainWindow
    MainWindow.__init__ = _originals["init"]
    MainWindow.apply_preset = _originals["apply_preset"]
    MainWindow._sync_controls_from_project = _originals["sync_controls"]
    MainWindow.ask_agent = _originals["ask_agent"]
    MainWindow._handle_agent_decision = _originals["handle_agent_decision"]
    MainWindow.reset_agent_chat = _originals["reset_agent_chat"]
    MainWindow.load_project_file = _originals["load_project_file"]
    for name in (
        "remove_video_selected",
        "remove_audio_selected",
        "_invalidate_agent_context",
    ):
        if hasattr(MainWindow, name):
            delattr(MainWindow, name)
    _originals.clear()
    _installed = False
