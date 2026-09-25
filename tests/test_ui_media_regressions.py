from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

import full_album_maker.media as media_module
from full_album_maker.media import MediaProbeError
from full_album_maker.project import Project
from full_album_maker.ui import MainWindow


def test_switching_locked_to_auto_preserves_auto_minimum():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    settings = window.project.settings
    settings.auto_speed = False
    settings.manual_speed = 1.5
    settings.min_speed = 0.5
    settings.loop_mode = "loop"
    window._sync_controls_from_project()

    assert window.min_speed.value() == pytest.approx(1.5)

    auto_index = window.slowmo_mode.findData("auto")
    window.slowmo_mode.setCurrentIndex(auto_index)
    app.processEvents()

    assert settings.auto_speed is True
    assert settings.min_speed == pytest.approx(0.5)
    assert settings.manual_speed == pytest.approx(1.5)
    assert window.min_speed.value() == pytest.approx(0.5)
    window.close()


def test_switching_auto_to_locked_restores_previous_manual_speed():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    settings = window.project.settings
    settings.auto_speed = True
    settings.min_speed = 0.4
    settings.manual_speed = 1.25
    window._sync_controls_from_project()

    assert window.min_speed.value() == pytest.approx(0.4)

    locked_index = window.slowmo_mode.findData("locked")
    window.slowmo_mode.setCurrentIndex(locked_index)
    app.processEvents()

    assert settings.auto_speed is False
    assert settings.min_speed == pytest.approx(0.4)
    assert settings.manual_speed == pytest.approx(1.25)
    assert window.min_speed.value() == pytest.approx(1.25)
    window.close()


def test_loop_change_does_not_mutate_auto_or_manual_speed():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    settings = window.project.settings
    settings.auto_speed = False
    settings.manual_speed = 1.5
    settings.min_speed = 0.35
    settings.loop_mode = "loop"
    window._sync_controls_from_project()

    pingpong_index = window.loop_mode.findData("pingpong")
    window.loop_mode.setCurrentIndex(pingpong_index)
    app.processEvents()

    assert settings.manual_speed == pytest.approx(1.5)
    assert settings.min_speed == pytest.approx(0.35)
    assert settings.loop_mode == "pingpong"
    window.close()


def test_video_probe_rejects_audio_only_container(monkeypatch, tmp_path):
    target = tmp_path / "audio_only.mp4"
    target.touch()
    monkeypatch.setattr(media_module, "ffprobe_path", lambda: "ffprobe")

    class Result:
        stdout = json.dumps(
            {
                "streams": [],
                "format": {"duration": "120.0"},
            }
        )

    monkeypatch.setattr(media_module.subprocess, "run", lambda *args, **kwargs: Result())

    with pytest.raises(MediaProbeError, match="tidak memiliki stream video"):
        media_module.probe_duration(str(target), "video")


def test_audio_probe_fallback_rejects_container_without_audio(monkeypatch, tmp_path):
    target = tmp_path / "video_only.m4a"
    target.touch()
    monkeypatch.setattr(media_module, "ffmpeg_path", lambda: "")
    monkeypatch.setattr(media_module, "ffprobe_path", lambda: "ffprobe")

    class Result:
        stdout = json.dumps(
            {
                "streams": [],
                "format": {"duration": "120.0"},
            }
        )

    monkeypatch.setattr(media_module.subprocess, "run", lambda *args, **kwargs: Result())

    with pytest.raises(MediaProbeError, match="tidak memiliki stream audio"):
        media_module.probe_duration(str(target), "audio")


def test_project_from_dict_rejects_unsupported_bitrates():
    data = Project().to_dict()
    data["settings"]["video_bitrate"] = "999M"

    with pytest.raises(ValueError, match="Video bitrate"):
        Project.from_dict(data)

    data = Project().to_dict()
    data["settings"]["audio_bitrate"] = "999k"

    with pytest.raises(ValueError, match="Audio bitrate"):
        Project.from_dict(data)
