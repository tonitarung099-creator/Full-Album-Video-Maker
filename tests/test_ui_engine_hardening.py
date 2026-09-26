from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QPushButton, QScrollArea

from full_album_maker.agent_actions import AgentAction, AgentDecision
from full_album_maker.controller import ProjectController
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
from full_album_maker.timeline import MAX_TIMELINE_CLIPS, TimelineEngine, TimelineError
from full_album_maker.ui import MainWindow
from full_album_maker.ui_hardening import install_ui_hardening, uninstall_ui_hardening
from full_album_maker.visual_feature import install_visual_feature, uninstall_visual_feature


@pytest.fixture(autouse=True)
def feature_stack():
    install_feature()
    install_playlist_hardening()
    install_visual_feature()
    install_engine_hardening()
    install_ui_hardening()
    try:
        yield
    finally:
        uninstall_ui_hardening()
        uninstall_engine_hardening()
        uninstall_visual_feature()
        uninstall_playlist_hardening()
        uninstall_feature()


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_window_is_scrollable_and_render_log_is_attached():
    app = _app()
    window = MainWindow()
    app.processEvents()

    assert window.minimumHeight() <= 620
    assert window.splitter.count() == 3
    assert all(isinstance(window.splitter.widget(i), QScrollArea) for i in range(3))
    assert window.log.parent() is not None
    assert window.log.document().maximumBlockCount() == 300
    assert window.log.maximumHeight() == 120

    button_texts = {button.text() for button in window.findChildren(QPushButton)}
    assert "Hapus Video" in button_texts
    assert "Hapus Lagu" in button_texts
    window.close()


def test_custom_preset_reflects_effective_settings_and_can_reapply_1080p():
    app = _app()
    window = MainWindow()
    window.project.settings.width = 1920
    window.project.settings.height = 1080
    window.project.settings.fps = 60
    window.project.settings.codec = "h265"
    window.project.settings.video_bitrate = "12M"
    window.project.settings.audio_bitrate = "320k"
    window.refresh()
    app.processEvents()

    assert window.preset.currentData() == "__custom__"

    preset_index = window.preset.findText("YouTube 1080p")
    assert preset_index >= 0
    window.preset.setCurrentIndex(preset_index)
    window.apply_preset()

    settings = window.project.settings
    assert (settings.width, settings.height) == (1920, 1080)
    assert settings.fps == 30
    assert settings.codec == "h264"
    assert settings.video_bitrate == "12M"
    assert settings.audio_bitrate == "320k"
    window.close()


def test_manual_remove_media_keeps_source_files(tmp_path):
    app = _app()
    video1 = tmp_path / "video1.mp4"
    video2 = tmp_path / "video2.mp4"
    audio1 = tmp_path / "audio1.wav"
    audio2 = tmp_path / "audio2.wav"
    for path in (video1, video2, audio1, audio2):
        path.write_bytes(b"source")

    window = MainWindow()
    project = Project(
        videos=[MediaItem(str(video1), 10.0), MediaItem(str(video2), 10.0)],
        audios=[MediaItem(str(audio1), 10.0), MediaItem(str(audio2), 10.0)],
    )
    window.project = project
    window.controller = ProjectController(project)
    window.refresh()

    window.video_list.setCurrentRow(0)
    window.remove_video_selected()
    window.audio_list.setCurrentRow(0)
    window.remove_audio_selected()
    app.processEvents()

    assert [Path(item.path).name for item in project.videos] == ["video2.mp4"]
    assert [Path(item.path).name for item in project.audios] == ["audio2.wav"]
    assert video1.read_bytes() == b"source"
    assert audio1.read_bytes() == b"source"
    window.close()


def test_stale_gemini_decision_after_reset_is_ignored():
    app = _app()
    window = MainWindow()
    window.project.settings.auto_speed = True
    window.project.settings.manual_speed = 1.0
    window.agent_busy = True
    old_epoch = window._agent_epoch

    window.reset_agent_chat()
    decision = AgentDecision(
        message="ubah slowmo",
        actions=[AgentAction("set_slowmo", {"speed": 0.4})],
    )
    setattr(decision, "_ui_epoch", old_epoch)
    window._handle_agent_decision(decision, "signature-lama")
    app.processEvents()

    assert window.project.settings.auto_speed is True
    assert window.project.settings.manual_speed == pytest.approx(1.0)
    assert window.agent_busy is False
    assert "diabaikan" in window.chat.toPlainText().casefold()
    window.close()


def test_reset_chat_discards_agent_object_without_mutating_it():
    app = _app()
    window = MainWindow()

    class OldAgent:
        def reset(self):
            raise AssertionError("Agent lama tidak boleh dimutasi saat worker mungkin masih memakai history.")

    window.agent = OldAgent()
    window.agent_busy = True
    before = window._agent_epoch
    window.reset_agent_chat()
    app.processEvents()

    assert window.agent is None
    assert window._agent_epoch == before + 1
    assert window.agent_busy is True
    assert "kedaluwarsa" in window.chat.toPlainText().casefold()
    window.close()


def test_readiness_uses_same_small_shortage_tolerance_as_timeline():
    project = Project(
        videos=[MediaItem("video.mp4", 20.0)],
        audios=[MediaItem("audio.wav", 20.02)],
    )
    project.settings.auto_speed = False
    project.settings.manual_speed = 1.0
    project.settings.loop_mode = "none"

    report = project.validation()

    assert project.needs_loop() is True
    assert any("terlalu pendek" in message.casefold() for message in report["errors"])


def test_readiness_rejects_bad_item_and_bad_settings():
    project = Project(
        videos=[MediaItem("ok.mp4", 10.0), MediaItem("bad.mp4", 0.0)],
        audios=[MediaItem("audio.wav", 10.0)],
    )
    project.settings.fps = 0

    errors = project.validation()["errors"]

    assert any("bad.mp4" in message for message in errors)
    assert any("fps" in message.casefold() for message in errors)


def test_first_visual_cycle_cannot_exceed_clip_limit():
    project = Project(
        videos=[
            MediaItem(f"video-{index:05d}.mp4", 1.0)
            for index in range(MAX_TIMELINE_CLIPS + 1)
        ],
        audios=[MediaItem("album.wav", float(MAX_TIMELINE_CLIPS + 1))],
    )
    project.settings.auto_speed = False
    project.settings.manual_speed = 1.0
    project.settings.loop_mode = "none"

    with pytest.raises(TimelineError, match=str(MAX_TIMELINE_CLIPS)):
        TimelineEngine().build(project)
