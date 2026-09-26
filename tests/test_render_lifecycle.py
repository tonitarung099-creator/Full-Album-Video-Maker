from __future__ import annotations

import os
import sys
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from full_album_maker.engine_hardening import (
    install_engine_hardening,
    uninstall_engine_hardening,
)
from full_album_maker.playlist_feature import install_feature, uninstall_feature
from full_album_maker.playlist_hardening import (
    install_playlist_hardening,
    uninstall_playlist_hardening,
)
from full_album_maker.render_lifecycle import (
    CANCEL_TOKEN,
    RenderCancelled,
    cancel_all_renderers,
    install_render_lifecycle,
    uninstall_render_lifecycle,
)
from full_album_maker.renderer import FFmpegRenderer
from full_album_maker.source_integrity import (
    install_source_integrity,
    uninstall_source_integrity,
)
from full_album_maker.ui import MainWindow
from full_album_maker.ui_hardening import install_ui_hardening, uninstall_ui_hardening
from full_album_maker.visual_feature import install_visual_feature, uninstall_visual_feature


@pytest.fixture(autouse=True)
def feature_stack():
    install_feature()
    install_playlist_hardening()
    install_visual_feature()
    install_engine_hardening()
    install_source_integrity()
    install_ui_hardening()
    install_render_lifecycle()
    try:
        yield
    finally:
        uninstall_render_lifecycle()
        uninstall_ui_hardening()
        uninstall_source_integrity()
        uninstall_engine_hardening()
        uninstall_visual_feature()
        uninstall_playlist_hardening()
        uninstall_feature()


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_cancel_terminates_running_subprocess():
    renderer = object.__new__(FFmpegRenderer)
    errors: list[BaseException] = []

    def run_process():
        try:
            renderer._run(
                [
                    sys.executable,
                    "-u",
                    "-c",
                    "import time; print('started', flush=True); time.sleep(30)",
                ]
            )
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=run_process)
    worker.start()

    deadline = time.time() + 5
    process = None
    while time.time() < deadline:
        process = getattr(renderer, "_fam_active_process", None)
        if process is not None and process.poll() is None:
            break
        time.sleep(0.01)

    assert process is not None
    assert process.poll() is None
    renderer.cancel()
    worker.join(timeout=10)

    assert not worker.is_alive()
    assert process.poll() is not None
    assert len(errors) == 1
    assert isinstance(errors[0], RenderCancelled)
    assert CANCEL_TOKEN in str(errors[0])


def test_pending_cancel_is_seen_before_renderer_starts_work():
    renderer = object.__new__(FFmpegRenderer)
    cancel_all_renderers()

    with pytest.raises(RenderCancelled, match="dibatalkan"):
        renderer.render()


def test_ui_exposes_cancel_button_and_suppresses_cancel_popup():
    app = _app()
    window = MainWindow()
    app.processEvents()

    assert hasattr(window, "cancel_render_btn")
    assert window.cancel_render_btn.isEnabled() is False

    window.render_busy = True
    window.refresh()
    assert window.cancel_render_btn.isEnabled() is True

    window._error(CANCEL_TOKEN + "Render dibatalkan oleh pengguna.")
    assert "Render dibatalkan oleh pengguna" in window.log.toPlainText()

    window.render_busy = False
    window._close_when_render_done = False
    window.close()


def test_close_during_render_requests_cancel_and_defers_close(monkeypatch):
    app = _app()
    window = MainWindow()
    window.render_busy = True

    monkeypatch.setattr(
        "full_album_maker.render_lifecycle.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.Yes,
    )

    class Event:
        def __init__(self):
            self.ignored = False
            self.accepted = False

        def ignore(self):
            self.ignored = True

        def accept(self):
            self.accepted = True

    event = Event()
    window.closeEvent(event)
    app.processEvents()

    assert event.ignored is True
    assert event.accepted is False
    assert window._close_when_render_done is True
    assert "Pembatalan render diminta" in window.log.toPlainText()

    window.render_busy = False
    window._close_when_render_done = False
    window.close()
