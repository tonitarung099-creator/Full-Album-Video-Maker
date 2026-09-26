from __future__ import annotations

import threading
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox, QPushButton, QScrollArea

from . import renderer as renderer_module
from . import ui as ui_module
from .renderer import FFmpegRenderer, RenderError


CANCEL_TOKEN = "__FAM_RENDER_CANCELLED__"
_installed = False
_originals: dict[str, Any] = {}
_active_lock = threading.RLock()
_active_renderers: set[FFmpegRenderer] = set()
_global_cancel = threading.Event()


class RenderCancelled(RenderError):
    pass


def _ensure_renderer_state(renderer: FFmpegRenderer) -> None:
    if not hasattr(renderer, "_fam_cancel_event"):
        renderer._fam_cancel_event = threading.Event()  # type: ignore[attr-defined]
    if not hasattr(renderer, "_fam_process_lock"):
        renderer._fam_process_lock = threading.RLock()  # type: ignore[attr-defined]
    if not hasattr(renderer, "_fam_active_process"):
        renderer._fam_active_process = None  # type: ignore[attr-defined]


def _terminate_process(process) -> None:
    if process is None:
        return
    try:
        if process.poll() is None:
            process.terminate()
    except Exception:
        pass


def _cancel_renderer(self: FFmpegRenderer) -> None:
    _ensure_renderer_state(self)
    self._fam_cancel_event.set()  # type: ignore[attr-defined]
    with self._fam_process_lock:  # type: ignore[attr-defined]
        process = self._fam_active_process  # type: ignore[attr-defined]
    _terminate_process(process)


def active_render_count() -> int:
    with _active_lock:
        return len(_active_renderers)


def cancel_all_renderers() -> int:
    # Keep the global flag set even when the worker has marked render_busy but
    # has not instantiated/registered its renderer yet. The next renderer that
    # enters render() will observe the pending cancellation immediately.
    _global_cancel.set()
    with _active_lock:
        renderers = list(_active_renderers)
    for renderer in renderers:
        renderer.cancel()  # type: ignore[attr-defined]
    return len(renderers)


def _patched_renderer_run(self: FFmpegRenderer, args: list[str], log=None) -> None:
    _ensure_renderer_state(self)
    cancel_event = self._fam_cancel_event  # type: ignore[attr-defined]
    if cancel_event.is_set() or _global_cancel.is_set():
        cancel_event.set()
        raise RenderCancelled(CANCEL_TOKEN + "Render dibatalkan oleh pengguna.")

    if log:
        log("Menjalankan FFmpeg…")

    process = renderer_module.subprocess.Popen(
        args,
        stdout=renderer_module.subprocess.PIPE,
        stderr=renderer_module.subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    with self._fam_process_lock:  # type: ignore[attr-defined]
        self._fam_active_process = process  # type: ignore[attr-defined]

    try:
        assert process.stdout is not None
        last_lines: list[str] = []
        for line in process.stdout:
            line = line.rstrip()
            if line:
                last_lines.append(line)
                last_lines = last_lines[-20:]
            if log and (
                "time=" in line
                or "Error" in line
                or "error" in line
                or "Invalid" in line
            ):
                log(line)
            if cancel_event.is_set() or _global_cancel.is_set():
                cancel_event.set()
                _terminate_process(process)
                break

        if cancel_event.is_set() or _global_cancel.is_set():
            cancel_event.set()
            _terminate_process(process)
            try:
                process.wait(timeout=5)
            except renderer_module.subprocess.TimeoutExpired:
                try:
                    process.kill()
                finally:
                    process.wait()
            raise RenderCancelled(CANCEL_TOKEN + "Render dibatalkan oleh pengguna.")

        code = process.wait()
        if code != 0:
            detail = "\n".join(last_lines[-8:])
            raise RenderError(
                f"FFmpeg keluar dengan kode {code}."
                + (f"\n{detail}" if detail else "")
            )
    finally:
        with self._fam_process_lock:  # type: ignore[attr-defined]
            if self._fam_active_process is process:  # type: ignore[attr-defined]
                self._fam_active_process = None  # type: ignore[attr-defined]


def _patched_renderer_render(self: FFmpegRenderer, *args, **kwargs):
    _ensure_renderer_state(self)
    cancel_event = self._fam_cancel_event  # type: ignore[attr-defined]
    cancel_event.clear()

    with _active_lock:
        _active_renderers.add(self)
        pending_cancel = _global_cancel.is_set()
    if pending_cancel:
        cancel_event.set()

    try:
        if cancel_event.is_set():
            raise RenderCancelled(CANCEL_TOKEN + "Render dibatalkan oleh pengguna.")
        return _originals["renderer_render"](self, *args, **kwargs)
    finally:
        with _active_lock:
            _active_renderers.discard(self)
            if not _active_renderers:
                _global_cancel.clear()


def _center_content(window):
    splitter = getattr(window, "splitter", None)
    if splitter is None or splitter.count() < 2:
        return None
    widget = splitter.widget(1)
    if isinstance(widget, QScrollArea):
        return widget.widget()
    return widget


def _sync_cancel_button(window) -> None:
    button = getattr(window, "cancel_render_btn", None)
    if button is None:
        return
    busy = bool(getattr(window, "render_busy", False))
    button.setEnabled(busy)
    button.setText("■  Membatalkan Render…" if busy and _global_cancel.is_set() else "■  Batalkan Render")


def _patched_ui_init(self, *args, **kwargs) -> None:
    _originals["ui_init"](self, *args, **kwargs)
    self._close_when_render_done = False

    content = _center_content(self)
    if content is not None and content.layout() is not None:
        self.cancel_render_btn = QPushButton("■  Batalkan Render")
        self.cancel_render_btn.setEnabled(False)
        self.cancel_render_btn.setToolTip(
            "Hentikan proses FFmpeg aktif. Output sementara dibersihkan dan hasil lama tetap aman."
        )
        self.cancel_render_btn.clicked.connect(self.cancel_render)
        content.layout().addWidget(self.cancel_render_btn)
    _sync_cancel_button(self)


def _cancel_render_ui(self) -> None:
    if not getattr(self, "render_busy", False):
        return
    self.log.appendPlainText("Pembatalan render diminta. Menghentikan FFmpeg aktif…")
    cancel_all_renderers()
    _sync_cancel_button(self)


def _patched_ui_render(self, *args, **kwargs):
    try:
        return _originals["ui_render"](self, *args, **kwargs)
    finally:
        _sync_cancel_button(self)


def _patched_agent_render(self, *args, **kwargs):
    try:
        return _originals["agent_render"](self, *args, **kwargs)
    finally:
        _sync_cancel_button(self)


def _patched_refresh(self, *args, **kwargs):
    result = _originals["ui_refresh"](self, *args, **kwargs)
    _sync_cancel_button(self)
    return result


def _patched_error(self, text) -> None:
    message = str(text)
    if message.startswith(CANCEL_TOKEN):
        clean = message[len(CANCEL_TOKEN) :].strip() or "Render dibatalkan."
        self.log.appendPlainText(clean)
        return
    _originals["ui_error"](self, text)


def _patched_render_done(self, path) -> None:
    _originals["render_done"](self, path)
    _sync_cancel_button(self)
    if getattr(self, "_close_when_render_done", False):
        self._close_when_render_done = False
        QTimer.singleShot(0, self.close)


def _patched_close_event(self, event) -> None:
    if getattr(self, "render_busy", False):
        answer = QMessageBox.question(
            self,
            "Render masih berjalan",
            "Render masih berjalan. Batalkan render dan tutup aplikasi setelah proses FFmpeg berhenti?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self._close_when_render_done = True
            self.cancel_render()
        event.ignore()
        return

    original = _originals.get("close_event")
    if original is not None:
        original(self, event)
    else:
        event.accept()


def install_render_lifecycle() -> None:
    global _installed
    if _installed:
        return

    MainWindow = ui_module.MainWindow
    _originals.update(
        {
            "renderer_run": FFmpegRenderer._run,
            "renderer_render": FFmpegRenderer.render,
            "ui_init": MainWindow.__init__,
            "ui_render": MainWindow.render,
            "agent_render": MainWindow._start_agent_render_default,
            "ui_refresh": MainWindow.refresh,
            "ui_error": MainWindow._error,
            "render_done": MainWindow._render_done,
            "close_event": MainWindow.__dict__.get("closeEvent"),
        }
    )

    FFmpegRenderer._run = _patched_renderer_run
    FFmpegRenderer.render = _patched_renderer_render
    FFmpegRenderer.cancel = _cancel_renderer  # type: ignore[attr-defined]

    MainWindow.__init__ = _patched_ui_init
    MainWindow.cancel_render = _cancel_render_ui
    MainWindow.render = _patched_ui_render
    MainWindow._start_agent_render_default = _patched_agent_render
    MainWindow.refresh = _patched_refresh
    MainWindow._error = _patched_error
    MainWindow._render_done = _patched_render_done
    MainWindow.closeEvent = _patched_close_event
    _installed = True


def uninstall_render_lifecycle() -> None:
    global _installed
    if not _installed:
        return

    FFmpegRenderer._run = _originals["renderer_run"]
    FFmpegRenderer.render = _originals["renderer_render"]
    if hasattr(FFmpegRenderer, "cancel"):
        delattr(FFmpegRenderer, "cancel")

    MainWindow = ui_module.MainWindow
    MainWindow.__init__ = _originals["ui_init"]
    MainWindow.render = _originals["ui_render"]
    MainWindow._start_agent_render_default = _originals["agent_render"]
    MainWindow.refresh = _originals["ui_refresh"]
    MainWindow._error = _originals["ui_error"]
    MainWindow._render_done = _originals["render_done"]
    if _originals["close_event"] is None:
        if "closeEvent" in MainWindow.__dict__:
            delattr(MainWindow, "closeEvent")
    else:
        MainWindow.closeEvent = _originals["close_event"]
    if hasattr(MainWindow, "cancel_render"):
        delattr(MainWindow, "cancel_render")

    with _active_lock:
        for renderer in list(_active_renderers):
            try:
                renderer.cancel()  # type: ignore[attr-defined]
            except Exception:
                pass
        _active_renderers.clear()
        _global_cancel.clear()

    _originals.clear()
    _installed = False
