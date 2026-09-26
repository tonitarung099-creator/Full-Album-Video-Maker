from __future__ import annotations

from pathlib import Path

import pytest

from full_album_maker.controller import ProjectController
from full_album_maker.playlist_feature import install_feature, uninstall_feature
from full_album_maker.playlist_hardening import (
    install_playlist_hardening,
    uninstall_playlist_hardening,
)
from full_album_maker.project import MediaItem, Project
from full_album_maker.timeline import TimelineError
from full_album_maker.visual_feature import (
    VisualPlaylistTimelineEngine,
    _ensure_project,
    _image_filters,
    _title_overlay_filter,
    images,
    install_visual_feature,
    uninstall_visual_feature,
    validate_visual_timeline,
    visual_project_signature,
    visual_settings,
)


@pytest.fixture(autouse=True)
def feature_stack():
    install_feature()
    install_playlist_hardening()
    install_visual_feature()
    try:
        yield
    finally:
        uninstall_visual_feature()
        uninstall_playlist_hardening()
        uninstall_feature()


def photo_project(*, audio_duration: float = 12.5, photo_count: int = 1) -> Project:
    project = Project(audios=[MediaItem(path="song.mp3", duration=audio_duration)])
    _ensure_project(project)
    for index in range(photo_count):
        item = MediaItem(path=f"photo-{index + 1}.jpg", duration=0.0)
        setattr(item, "width", 1920)
        setattr(item, "height", 1080)
        images(project).append(item)
    return project


def test_photo_only_per_song_builds_exact_audio_length():
    project = photo_project(audio_duration=12.5)
    visual_settings(project)["visual_mode"] = "per_song"

    plan = VisualPlaylistTimelineEngine().build(project)

    assert plan.duration == pytest.approx(12.5)
    assert len(plan.audio_clips) == 1
    assert len(plan.video_clips) == 1
    assert plan.video_clips[0].kind == "image"
    assert plan.video_clips[0].timeline_in == pytest.approx(0.0)
    assert plan.video_clips[0].timeline_out == pytest.approx(12.5)
    assert plan.validate() == []
    assert validate_visual_timeline(plan, project) == []


def test_photo_only_validation_does_not_require_video_file():
    project = photo_project()
    report = project.validation()

    assert "Belum ada footage video." not in report["errors"]
    assert "Durasi footage tidak valid." not in report["errors"]


def test_sequential_photos_repeat_to_fill_album():
    project = photo_project(audio_duration=25.0, photo_count=2)
    settings = visual_settings(project)
    settings["visual_mode"] = "sequential"
    settings["photo_duration"] = 10.0
    project.settings.loop_mode = "auto"

    plan = VisualPlaylistTimelineEngine().build(project)

    assert [clip.kind for clip in plan.video_clips] == ["image", "image", "image"]
    assert [clip.timeline_duration for clip in plan.video_clips] == pytest.approx(
        [10.0, 10.0, 5.0]
    )
    assert plan.video_clips[-1].cycle == 1
    assert plan.video_duration == pytest.approx(25.0)


def test_audio_display_metadata_is_bound_to_timeline_title():
    project = photo_project()
    setattr(project.audios[0], "display_title", "Judul Bersih")
    setattr(project.audios[0], "display_artist", "Penyanyi")
    visual_settings(project)["visual_mode"] = "per_song"

    plan = VisualPlaylistTimelineEngine().build(project)

    assert plan.audio_clips[0].name == "Judul Bersih"


def test_visual_project_roundtrip_keeps_images_titles_and_settings():
    project = photo_project(photo_count=2)
    setattr(project.audios[0], "display_title", "Lagu Final")
    setattr(project.audios[0], "display_artist", "Artis Final")
    setattr(project.audios[0], "cover_path", images(project)[1].path)
    visual_settings(project)["visual_mode"] = "per_song"
    visual_settings(project)["title_animation"] = "slide"
    setattr(project, "_visual_order", [images(project)[1].path, images(project)[0].path])

    restored = Project.from_dict(project.to_dict())

    assert len(images(restored)) == 2
    assert [Path(item.path).name for item in images(restored)] == [
        "photo-1.jpg",
        "photo-2.jpg",
    ]
    assert getattr(restored.audios[0], "display_title") == "Lagu Final"
    assert getattr(restored.audios[0], "display_artist") == "Artis Final"
    assert Path(getattr(restored.audios[0], "cover_path")).name == "photo-2.jpg"
    assert visual_settings(restored)["visual_mode"] == "per_song"
    assert visual_settings(restored)["title_animation"] == "slide"
    assert [Path(value).name for value in getattr(restored, "_visual_order")] == [
        "photo-2.jpg",
        "photo-1.jpg",
    ]


def test_old_project_without_visual_fields_still_loads():
    raw = Project(
        videos=[MediaItem(path="video.mp4", duration=5.0)],
        audios=[MediaItem(path="song.mp3", duration=5.0)],
    ).to_dict()
    raw.pop("images", None)
    raw.pop("visual_settings", None)
    raw.pop("visual_order", None)

    restored = Project.from_dict(raw)

    assert images(restored) == []
    assert visual_settings(restored)["visual_mode"] == "sequential"


def test_signature_changes_when_title_or_visual_setting_changes():
    project = photo_project()
    before = visual_project_signature(project)

    visual_settings(project)["title_animation"] = "slide"
    after_animation = visual_project_signature(project)
    setattr(project.audios[0], "display_title", "Nama Baru")
    after_title = visual_project_signature(project)

    assert after_animation != before
    assert after_title != after_animation


def test_missing_explicit_song_visual_fails_instead_of_guessing():
    project = photo_project()
    visual_settings(project)["visual_mode"] = "per_song"
    setattr(project.audios[0], "visual_path", "foto-yang-sudah-hilang.jpg")

    with pytest.raises(TimelineError, match="sudah tidak tersedia"):
        VisualPlaylistTimelineEngine().build(project)


def test_controller_visual_actions_change_project_and_signature():
    project = photo_project(photo_count=2)
    controller = ProjectController(project)
    before = visual_project_signature(project)

    controller.execute("set_visual_mode", {"mode": "per_song"})
    controller.execute(
        "set_title_style",
        {"mode": "intro6", "animation": "fade"},
    )
    controller.execute(
        "assign_song_visual",
        {"song_position": 1, "image_position": 2},
    )

    assert visual_settings(project)["visual_mode"] == "per_song"
    assert visual_settings(project)["title_mode"] == "intro6"
    assert Path(getattr(project.audios[0], "visual_path")).name == "photo-2.jpg"
    assert visual_project_signature(project) != before


def test_photo_filter_defaults_to_blurred_background_and_zoom():
    project = photo_project()
    chain = _image_filters(project, images(project)[0], 10.0)

    assert "boxblur=" in chain
    assert "zoompan=" in chain
    assert "setsar=1" in chain


def test_title_overlay_has_fade_and_safe_bottom_left_position():
    project = photo_project()
    visual_settings(project)["title_mode"] = "full"
    visual_settings(project)["title_animation"] = "fade"

    chain = _title_overlay_filter(project, 8.0)

    assert "fade=t=in" in chain
    assert "fade=t=out" in chain
    assert "main_w*0.05" in chain
    assert "main_h-overlay_h-main_h*0.05" in chain
