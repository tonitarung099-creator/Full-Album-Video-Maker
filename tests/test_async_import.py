from __future__ import annotations

import os
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from full_album_maker.async_import import install_async_import, uninstall_async_import
from full_album_maker.controller import ProjectController
from full_album_maker.engine_hardening import install_engine_hardening, uninstall_engine_hardening
from full_album_maker.playlist_feature import install_feature, uninstall_feature
from full_album_maker.playlist_hardening import install_playlist_hardening, uninstall_playlist_hardening
from full_album_maker.project import Project
from full_album_maker.project_dirty import install_project_dirty_state, uninstall_project_dirty_state
from full_album_maker.render_lifecycle import install_render_lifecycle, uninstall_render_lifecycle
from full_album_maker.source_integrity import install_source_integrity, uninstall_source_integrity
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
    install_async_import()
    try:
        yield
    finally:
        uninstall_async_import()
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


def _wait_jobs(window, timeout: float = 5.0) -> None:
    app = _app()
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if window._import_job_count == 0:
            return
        time.sleep(0.01)
    raise AssertionError("Import worker tidak selesai dalam batas waktu tes.")


def _close_without_dirty_prompt(window) -> None:
    window._saved_project_state = None
    window.close()
    _app().processEvents()


def test_video_probe_runs_off_ui_thread_and_commits_after_completion(tmp_path, monkeypatch):
    app = _app()
    source = tmp_path / "slow-video.mp4"
    source.write_bytes(b"video")
    entered = threading.Event()
    release = threading.Event()

    def slow_probe(path, kind=None):
        assert kind == "video"
        entered.set()
        assert release.wait(timeout=5)
        return 12.5

    monkeypatch.setattr("full_album_maker.async_import.probe_duration", slow_probe)
    monkeypatch.setattr(
        "full_album_maker.async_import.QFileDialog.getOpenFileNames",
        lambda *args, **kwargs: ([str(source)], "Video"),
    )

    window = MainWindow()
    window.add_video()

    assert entered.wait(timeout=2)
    assert window._import_job_count == 1
    assert window.project.videos == []

    # If probing were still on the UI thread, execution could not reach here
    # until release was set. Mutating/refeshing another control proves the call
    # returned while the worker remains blocked.
    window.project.settings.fps = 60
    window.refresh()
    app.processEvents()
    assert window.project.settings.fps == 60

    release.set()
    _wait_jobs(window)

    assert len(window.project.videos) == 1
    assert Path(window.project.videos[0].path).name == "slow-video.mp4"
    assert window.project.videos[0].duration == pytest.approx(12.5)
    assert window.timeline_plan is None
    assert "background" in window.log.toPlainText().casefold()
    _close_without_dirty_prompt(window)


def test_audio_import_probes_metadata_in_worker(tmp_path, monkeypatch):
    source = tmp_path / "song.mp3"
    source.write_bytes(b"audio")

    monkeypatch.setattr(
        "full_album_maker.async_import.probe_duration",
        lambda path, kind=None: 7.25,
    )
    monkeypatch.setattr(
        "full_album_maker.async_import.visual_feature_module.probe_audio_tags",
        lambda path: ("Judul Metadata", "Artis Metadata"),
    )
    monkeypatch.setattr(
        "full_album_maker.async_import.QFileDialog.getOpenFileNames",
        lambda *args, **kwargs: ([str(source)], "Audio"),
    )

    window = MainWindow()
    window.add_audio()
    _wait_jobs(window)

    assert len(window.project.audios) == 1
    item = window.project.audios[0]
    assert item.duration == pytest.approx(7.25)
    assert getattr(item, "display_title") == "Judul Metadata"
    assert getattr(item, "display_artist") == "Artis Metadata"
    assert getattr(item, "metadata_probed") is True
    _close_without_dirty_prompt(window)


def test_image_import_keeps_dimensions_and_visual_order(tmp_path, monkeypatch):
    source = tmp_path / "cover.webp"
    source.write_bytes(b"image")

    monkeypatch.setattr(
        "full_album_maker.async_import.visual_feature_module.probe_image",
        lambda path: {"width": 1200, "height": 1600, "format": "webp"},
    )
    monkeypatch.setattr(
        "full_album_maker.async_import.QFileDialog.getOpenFileNames",
        lambda *args, **kwargs: ([str(source)], "Foto"),
    )

    window = MainWindow()
    window.add_image()
    _wait_jobs(window)

    assert len(getattr(window.project, "images")) == 1
    image = getattr(window.project, "images")[0]
    assert getattr(image, "width") == 1200
    assert getattr(image, "height") == 1600
    assert getattr(window.project, "_visual_order") == [str(source)]
    _close_without_dirty_prompt(window)


def test_pending_duplicate_is_not_started_twice(tmp_path, monkeypatch):
    source = tmp_path / "duplicate.mp4"
    source.write_bytes(b"video")
    entered = threading.Event()
    release = threading.Event()
    calls = 0

    def slow_probe(path, kind=None):
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(timeout=5)
        return 4.0

    monkeypatch.setattr("full_album_maker.async_import.probe_duration", slow_probe)
    monkeypatch.setattr(
        "full_album_maker.async_import.QFileDialog.getOpenFileNames",
        lambda *args, **kwargs: ([str(source)], "Video"),
    )

    window = MainWindow()
    window.add_video()
    assert entered.wait(timeout=2)
    window.add_video()

    assert window._import_job_count == 1
    release.set()
    _wait_jobs(window)

    assert calls == 1
    assert len(window.project.videos) == 1
    assert "pending dilewati" in window.log.toPlainText().casefold()
    _close_without_dirty_prompt(window)


def test_finished_import_is_discarded_if_project_changed(tmp_path, monkeypatch):
    source = tmp_path / "old-project-video.mp4"
    source.write_bytes(b"video")
    entered = threading.Event()
    release = threading.Event()

    def slow_probe(path, kind=None):
        entered.set()
        assert release.wait(timeout=5)
        return 9.0

    monkeypatch.setattr("full_album_maker.async_import.probe_duration", slow_probe)
    monkeypatch.setattr(
        "full_album_maker.async_import.QFileDialog.getOpenFileNames",
        lambda *args, **kwargs: ([str(source)], "Video"),
    )

    window = MainWindow()
    window.add_video()
    assert entered.wait(timeout=2)

    replacement = Project()
    window.project = replacement
    window.controller = ProjectController(replacement)
    release.set()
    _wait_jobs(window)

    assert replacement.videos == []
    assert "diabaikan karena proyek aktif sudah berganti" in window.log.toPlainText().casefold()
    _close_without_dirty_prompt(window)
