from __future__ import annotations

import os
from pathlib import Path

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
from full_album_maker.project import MediaItem, Project
from full_album_maker.project_dirty import (
    install_project_dirty_state,
    uninstall_project_dirty_state,
)
from full_album_maker.project_io import save_project
from full_album_maker.render_lifecycle import (
    install_render_lifecycle,
    uninstall_render_lifecycle,
)
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
    install_project_dirty_state()
    try:
        yield
    finally:
        uninstall_project_dirty_state()
        uninstall_render_lifecycle()
        uninstall_ui_hardening()
        uninstall_source_integrity()
        uninstall_engine_hardening()
        uninstall_visual_feature()
        uninstall_playlist_hardening()
        uninstall_feature()


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


class _Event:
    def __init__(self):
        self.ignored = False
        self.accepted = False

    def ignore(self):
        self.ignored = True

    def accept(self):
        self.accepted = True


def test_project_starts_clean_and_mutation_marks_title_dirty():
    app = _app()
    window = MainWindow()
    app.processEvents()

    assert window.is_project_dirty() is False
    assert not window.windowTitle().endswith("*")

    window.project.settings.fps = 60
    window.refresh()
    app.processEvents()

    assert window.is_project_dirty() is True
    assert window.windowTitle().endswith("*")
    window._saved_project_state = None
    window.close()


def test_save_resets_dirty_baseline(tmp_path, monkeypatch):
    app = _app()
    window = MainWindow()
    window.project.settings.fps = 60
    window.refresh()
    destination = tmp_path / "saved-project.json"

    monkeypatch.setattr(
        "full_album_maker.project_dirty.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(destination), "Full Album Project (*.json)"),
    )

    assert window.is_project_dirty() is True
    assert window.save_project_file() is True
    app.processEvents()

    assert destination.exists()
    assert window.is_project_dirty() is False
    assert destination.name in window.windowTitle()
    assert not window.windowTitle().endswith("*")
    window.close()


def test_close_cancel_keeps_dirty_window_open(monkeypatch):
    app = _app()
    window = MainWindow()
    window.project.settings.fps = 60
    window.refresh()

    monkeypatch.setattr(
        "full_album_maker.project_dirty.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.Cancel,
    )
    event = _Event()
    window.closeEvent(event)
    app.processEvents()

    assert event.ignored is True
    assert event.accepted is False
    assert window.is_project_dirty() is True
    window._saved_project_state = None
    window.close()


def test_close_discard_accepts_close(monkeypatch):
    app = _app()
    window = MainWindow()
    window.project.settings.fps = 60
    window.refresh()

    monkeypatch.setattr(
        "full_album_maker.project_dirty.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.Discard,
    )
    event = _Event()
    window.closeEvent(event)
    app.processEvents()

    assert event.accepted is True
    assert event.ignored is False


def test_close_save_but_cancel_save_dialog_does_not_close(monkeypatch):
    app = _app()
    window = MainWindow()
    window.project.settings.fps = 60
    window.refresh()

    monkeypatch.setattr(
        "full_album_maker.project_dirty.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.Save,
    )
    monkeypatch.setattr(
        "full_album_maker.project_dirty.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: ("", ""),
    )
    event = _Event()
    window.closeEvent(event)
    app.processEvents()

    assert event.ignored is True
    assert event.accepted is False
    assert window.is_project_dirty() is True
    window._saved_project_state = None
    window.close()


def test_open_project_cancel_unsaved_never_opens_file_dialog(monkeypatch):
    app = _app()
    window = MainWindow()
    original_project = window.project
    window.project.settings.fps = 60
    window.refresh()
    open_dialog_calls = []

    monkeypatch.setattr(
        "full_album_maker.project_dirty.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.Cancel,
    )
    monkeypatch.setattr(
        "full_album_maker.ui.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: open_dialog_calls.append(True) or ("", ""),
    )

    assert window.load_project_file() is False
    assert open_dialog_calls == []
    assert window.project is original_project
    window._saved_project_state = None
    window.close()


def test_open_project_after_discard_loads_new_clean_baseline(tmp_path, monkeypatch):
    app = _app()
    source = tmp_path / "other-project.json"
    incoming = Project(
        videos=[MediaItem(path="incoming-video.mp4", duration=5.0)],
        audios=[MediaItem(path="incoming-audio.wav", duration=5.0)],
    )
    save_project(str(source), incoming)

    window = MainWindow()
    window.project.settings.fps = 60
    window.refresh()

    monkeypatch.setattr(
        "full_album_maker.project_dirty.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.Discard,
    )
    monkeypatch.setattr(
        "full_album_maker.ui.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(source), "Full Album Project (*.json)"),
    )

    assert window.load_project_file() is True
    app.processEvents()

    assert window.project.settings.fps == 30
    assert [item.path for item in window.project.videos] == ["incoming-video.mp4"]
    assert window.is_project_dirty() is False
    window.close()


def test_open_is_blocked_while_render_is_active(monkeypatch):
    app = _app()
    window = MainWindow()
    window.render_busy = True
    errors: list[str] = []
    window._error = errors.append

    assert window.load_project_file() is False
    assert errors
    assert "render" in errors[0].casefold()

    window.render_busy = False
    window.close()
