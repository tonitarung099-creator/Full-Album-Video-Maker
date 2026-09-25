from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

import full_album_maker.media as media_module
import full_album_maker.renderer as renderer_module
from full_album_maker.agent_actions import AgentAction, AgentDecision, AppIntentExecutor
from full_album_maker.controller import ProjectController
from full_album_maker.project import MediaItem, Project
from full_album_maker.renderer import FFmpegRenderer, RenderError
from full_album_maker.timeline import (
    TimelineEngine,
    TimelineError,
    TimelinePlan,
    project_signature,
    validate_timeline_against_project,
)
from full_album_maker.ui import MainWindow


def test_executor_defers_auto_build_until_final_project_state(tmp_path):
    project = Project(
        videos=[MediaItem("video.mp4", 2400.0)],
        audios=[MediaItem("album.mp3", 3600.0)],
    )
    executor = AppIntentExecutor(
        project,
        timeline_output_path=str(tmp_path / "Timeline_Auto.json"),
    )

    execution = executor.execute(
        [
            AgentAction("auto_build_timeline", {}),
            AgentAction("set_slowmo", {"speed": 0.5}),
        ]
    )

    assert project.settings.auto_speed is False
    assert project.settings.manual_speed == pytest.approx(0.5)
    assert execution.timeline_plan is not None
    assert execution.timeline_plan.planned_speed == pytest.approx(0.5)
    assert execution.timeline_plan.project_signature == project_signature(project)
    assert execution.timeline_plan.auto_cut_seconds == pytest.approx(1200.0)


def test_timeline_rejects_nan_and_zero_speed_without_crashing():
    project = Project(
        videos=[MediaItem("video.mp4", 10.0)],
        audios=[MediaItem("audio.wav", 10.0)],
    )
    plan = TimelineEngine().build(project)

    data = plan.to_dict()
    data["duration"] = float("nan")
    with pytest.raises(TimelineError, match="tidak valid"):
        TimelinePlan.from_dict(data)

    plan = TimelineEngine().build(project)
    plan.video_clips[0].speed = 0.0
    errors = plan.validate()
    assert any("speed tidak valid" in error for error in errors)

    # Project-aware validation must return errors instead of dividing by zero.
    errors = validate_timeline_against_project(plan, project)
    assert errors


def test_timeline_rejects_malformed_source_index_type():
    project = Project(
        videos=[MediaItem("video.mp4", 10.0)],
        audios=[MediaItem("audio.wav", 10.0)],
    )
    data = TimelineEngine().build(project).to_dict()
    data["video_clips"][0]["source_index"] = "0"

    with pytest.raises(TimelineError, match="source_index"):
        TimelinePlan.from_dict(data)


def test_renderer_failure_keeps_previous_destination(monkeypatch, tmp_path):
    monkeypatch.setattr(renderer_module, "ffmpeg_path", lambda: "ffmpeg")

    video = tmp_path / "source.mp4"
    audio = tmp_path / "source.wav"
    video.touch()
    audio.touch()

    project = Project(
        videos=[MediaItem(str(video), 10.0)],
        audios=[MediaItem(str(audio), 10.0)],
    )
    plan = TimelineEngine().build(project)
    renderer = FFmpegRenderer(project, plan)

    monkeypatch.setattr(renderer, "_ensure_encoder", lambda: None)
    monkeypatch.setattr(renderer, "_build_audio_from_timeline", lambda *args, **kwargs: None)
    monkeypatch.setattr(renderer, "_build_video_from_timeline", lambda *args, **kwargs: None)

    destination = tmp_path / "existing.mp4"
    destination.write_bytes(b"previous-good-render")

    def fail_final(video_path, audio_path, dest, log=None):
        Path(dest).write_bytes(b"partial-new-render")
        raise RenderError("simulated mux failure")

    monkeypatch.setattr(renderer, "_build_final", fail_final)

    with pytest.raises(RenderError, match="simulated mux failure"):
        renderer.render(str(destination))

    assert destination.read_bytes() == b"previous-good-render"
    assert not list(tmp_path.glob(".existing.*.rendering.mp4"))


def test_renderer_success_atomically_replaces_destination(monkeypatch, tmp_path):
    monkeypatch.setattr(renderer_module, "ffmpeg_path", lambda: "ffmpeg")

    video = tmp_path / "source.mp4"
    audio = tmp_path / "source.wav"
    video.touch()
    audio.touch()

    project = Project(
        videos=[MediaItem(str(video), 10.0)],
        audios=[MediaItem(str(audio), 10.0)],
    )
    plan = TimelineEngine().build(project)
    renderer = FFmpegRenderer(project, plan)

    monkeypatch.setattr(renderer, "_ensure_encoder", lambda: None)
    monkeypatch.setattr(renderer, "_build_audio_from_timeline", lambda *args, **kwargs: None)
    monkeypatch.setattr(renderer, "_build_video_from_timeline", lambda *args, **kwargs: None)

    def successful_final(video_path, audio_path, dest, log=None):
        Path(dest).write_bytes(b"new-good-render")

    monkeypatch.setattr(renderer, "_build_final", successful_final)

    destination = tmp_path / "existing.mp4"
    destination.write_bytes(b"old-render")
    result = renderer.render(str(destination))

    assert result == str(destination)
    assert destination.read_bytes() == b"new-good-render"
    assert not list(tmp_path.glob(".existing.*.rendering.mp4"))


def test_video_duration_uses_duration_ts_before_container(monkeypatch, tmp_path):
    media = tmp_path / "stream-duration.mkv"
    media.touch()
    monkeypatch.setattr(media_module, "ffprobe_path", lambda: "ffprobe")

    class Result:
        stdout = json.dumps(
            {
                "streams": [
                    {
                        "duration": "N/A",
                        "duration_ts": 25,
                        "time_base": "1/25",
                        "tags": {},
                    }
                ],
                "format": {"duration": "3.000"},
            }
        )

    monkeypatch.setattr(
        media_module.subprocess,
        "run",
        lambda *args, **kwargs: Result(),
    )

    assert media_module.probe_duration(str(media), "video") == pytest.approx(1.0)


def test_ui_rolls_back_project_if_plan_application_fails(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])

    window = MainWindow()
    project = Project(
        videos=[MediaItem("video.mp4", 2400.0)],
        audios=[MediaItem("album.mp3", 3600.0)],
    )
    window.project = project
    window.controller = ProjectController(project)
    window.refresh()

    monkeypatch.setattr(
        "full_album_maker.ui.output_dir",
        lambda: tmp_path,
    )

    def fail_apply(plan):
        raise RuntimeError("simulated UI apply failure")

    monkeypatch.setattr(window, "apply_timeline_plan", fail_apply)
    errors = []
    window._error = errors.append

    decision = AgentDecision(
        message="Saya pahami.",
        actions=[
            AgentAction("set_slowmo", {"speed": 0.5}),
            AgentAction("auto_build_timeline", {}),
        ],
    )
    signature = project_signature(window.project)

    window._handle_agent_decision(decision, signature)
    app.processEvents()

    assert errors
    assert window.project.settings.auto_speed is True
    assert window.project.settings.manual_speed == pytest.approx(1.0)
    assert window.timeline_plan is None
    assert window.timeline_ready is False
    window.close()
