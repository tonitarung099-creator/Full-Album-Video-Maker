from __future__ import annotations

import json

import pytest

from full_album_maker.project import MediaItem, Project
from full_album_maker.timeline import (
    TimelineEngine,
    TimelineError,
    TimelinePlan,
    load_timeline,
    project_signature,
    save_timeline,
    timeline_matches_project,
    validate_timeline_against_project,
)


def _project(video_seconds: float, audio_seconds: float) -> Project:
    return Project(
        videos=[MediaItem("video.mp4", video_seconds)],
        audios=[MediaItem("song.mp3", audio_seconds)],
    )


def test_locked_half_speed_auto_cut_matches_user_example():
    project = _project(2400.0, 3600.0)  # 40 min footage, 1 hour album
    project.settings.auto_speed = False
    project.settings.manual_speed = 0.5
    project.settings.loop_mode = "loop"

    plan = TimelineEngine().build(project)

    assert plan.duration == pytest.approx(3600.0)
    assert plan.planned_speed == pytest.approx(0.5)
    assert plan.adjusted_video_duration == pytest.approx(4800.0)
    assert plan.auto_cut_seconds == pytest.approx(1200.0)
    assert plan.loop_fill_seconds == pytest.approx(0.0)
    assert plan.loop_mode == "none"
    assert len(plan.video_clips) == 1

    clip = plan.video_clips[0]
    assert clip.source_in == pytest.approx(0.0)
    assert clip.source_out == pytest.approx(1800.0)  # only 30 min source needed
    assert clip.timeline_in == pytest.approx(0.0)
    assert clip.timeline_out == pytest.approx(3600.0)
    assert clip.speed == pytest.approx(0.5)


def test_auto_fit_uses_entire_footage_without_cut_or_loop():
    project = _project(2400.0, 3600.0)
    project.settings.auto_speed = True
    project.settings.min_speed = 0.5

    plan = TimelineEngine().build(project)

    assert plan.planned_speed == pytest.approx(2 / 3)
    assert plan.auto_cut_seconds == pytest.approx(0.0)
    assert plan.loop_fill_seconds == pytest.approx(0.0)
    assert len(plan.video_clips) == 1
    assert plan.video_clips[0].source_out == pytest.approx(2400.0)
    assert plan.video_clips[0].timeline_out == pytest.approx(3600.0)


def test_short_footage_loops_only_remaining_duration():
    project = _project(1200.0, 3600.0)  # 20 min source
    project.settings.auto_speed = True
    project.settings.min_speed = 0.5
    project.settings.loop_mode = "loop"

    plan = TimelineEngine().build(project)

    assert plan.planned_speed == pytest.approx(0.5)
    assert plan.adjusted_video_duration == pytest.approx(2400.0)
    assert plan.loop_fill_seconds == pytest.approx(1200.0)
    assert plan.needs_loop is True
    assert len(plan.video_clips) == 2

    first, second = plan.video_clips
    assert first.kind == "source"
    assert first.timeline_out == pytest.approx(2400.0)
    assert second.kind == "loop"
    assert second.timeline_in == pytest.approx(2400.0)
    assert second.timeline_out == pytest.approx(3600.0)
    assert second.source_out == pytest.approx(600.0)


def test_pingpong_reverses_source_range_for_partial_fill():
    project = _project(1200.0, 3600.0)
    project.settings.auto_speed = True
    project.settings.min_speed = 0.5
    project.settings.loop_mode = "pingpong"

    plan = TimelineEngine().build(project)

    assert len(plan.video_clips) == 2
    first, second = plan.video_clips
    assert first.direction == "forward"
    assert second.direction == "reverse"
    assert second.kind == "pingpong"
    assert second.timeline_in == pytest.approx(2400.0)
    assert second.timeline_out == pytest.approx(3600.0)
    assert second.source_in == pytest.approx(600.0)
    assert second.source_out == pytest.approx(1200.0)


def test_multiple_video_sources_are_contiguous_and_final_clip_is_trimmed():
    project = Project(
        videos=[
            MediaItem("a.mp4", 600.0),
            MediaItem("b.mp4", 900.0),
            MediaItem("c.mp4", 1200.0),
        ],
        audios=[MediaItem("album.mp3", 2000.0)],
    )
    project.settings.auto_speed = False
    project.settings.manual_speed = 1.0

    plan = TimelineEngine().build(project)

    assert [x.source_index for x in plan.video_clips] == [0, 1, 2]
    assert plan.video_clips[0].timeline_out == pytest.approx(600.0)
    assert plan.video_clips[1].timeline_in == pytest.approx(600.0)
    assert plan.video_clips[1].timeline_out == pytest.approx(1500.0)
    assert plan.video_clips[2].timeline_in == pytest.approx(1500.0)
    assert plan.video_clips[2].timeline_out == pytest.approx(2000.0)
    assert plan.video_clips[2].source_out == pytest.approx(500.0)
    assert plan.auto_cut_seconds == pytest.approx(700.0)


def test_audio_track_is_master_and_never_trimmed():
    project = Project(
        videos=[MediaItem("video.mp4", 100.0)],
        audios=[
            MediaItem("01.mp3", 30.0),
            MediaItem("02.mp3", 40.0),
            MediaItem("03.mp3", 50.0),
        ],
    )
    project.settings.auto_speed = True
    project.settings.min_speed = 0.5

    plan = TimelineEngine().build(project)

    assert plan.duration == pytest.approx(120.0)
    assert [(x.timeline_in, x.timeline_out) for x in plan.audio_clips] == [
        pytest.approx((0.0, 30.0)),
        pytest.approx((30.0, 70.0)),
        pytest.approx((70.0, 120.0)),
    ]
    assert [x.source_out for x in plan.audio_clips] == pytest.approx([30.0, 40.0, 50.0])


def test_loop_none_rejects_short_video():
    project = _project(100.0, 500.0)
    project.settings.auto_speed = False
    project.settings.manual_speed = 1.0
    project.settings.loop_mode = "none"

    with pytest.raises(TimelineError, match="mode loop dimatikan"):
        TimelineEngine().build(project)


def test_timeline_json_roundtrip_and_signature(tmp_path):
    project = _project(100.0, 150.0)
    project.settings.min_speed = 0.5
    plan = TimelineEngine().build(project)

    path = save_timeline(str(tmp_path / "timeline"), plan)
    loaded = load_timeline(path)

    assert isinstance(loaded, TimelinePlan)
    assert loaded.to_dict() == plan.to_dict()
    assert timeline_matches_project(loaded, project) is True
    assert loaded.project_signature == project_signature(project)

    raw = json.loads((tmp_path / "timeline.json").read_text(encoding="utf-8"))
    assert raw["version"] == 1
    assert raw["duration"] == pytest.approx(150.0)


def test_timeline_signature_detects_project_change():
    project = _project(100.0, 150.0)
    plan = TimelineEngine().build(project)
    assert timeline_matches_project(plan, project) is True

    project.audios.append(MediaItem("extra.mp3", 10.0))
    assert timeline_matches_project(plan, project) is False


def test_plan_validation_catches_gap():
    project = _project(100.0, 100.0)
    plan = TimelineEngine().build(project)
    plan.video_clips[0].timeline_in = 1.0
    assert any("tidak sambung" in x for x in plan.validate())


def test_timeline_project_validation_rejects_tampered_source_mapping():
    project = _project(100.0, 80.0)
    plan = TimelineEngine().build(project)
    plan.video_clips[0].source_out = 120.0
    plan.video_clips[0].timeline_out = 120.0

    errors = validate_timeline_against_project(plan, project)
    assert any("melewati batas durasi source" in x for x in errors)
