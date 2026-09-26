from __future__ import annotations

from pathlib import Path

import pytest

from full_album_maker import agent_actions as agent_actions_module
from full_album_maker import gemini_agent as gemini_agent_module
from full_album_maker import timeline as timeline_module
from full_album_maker.agent_actions import AgentAction, AppIntentExecutor
from full_album_maker.controller import ProjectController
from full_album_maker.playlist_feature import (
    PlaylistSelectionError,
    PlaylistTimelineEngine,
    active_audio_indices,
    get_active_audio_paths,
    install_feature,
    select_audio_titles,
    uninstall_feature,
)
from full_album_maker.project import MediaItem, Project


@pytest.fixture
def feature():
    install_feature()
    try:
        yield
    finally:
        uninstall_feature()


def _library(count: int = 200) -> list[MediaItem]:
    return [
        MediaItem(f"/media/{index:03d} - Lagu Pilihan {index:03d}.mp3", 180.0 + index)
        for index in range(1, count + 1)
    ]


def test_matcher_selects_twenty_from_two_hundred_without_mutating_media():
    media = _library(200)
    titles = [f"Lagu Pilihan {index:03d}" for index in range(5, 25)]

    selection = select_audio_titles(media, titles)

    assert len(media) == 200
    assert selection.count == 20
    assert [Path(path).stem for path in selection.selected_paths] == [
        f"{index:03d} - Lagu Pilihan {index:03d}" for index in range(5, 25)
    ]


def test_matcher_accepts_track_numbers_extensions_case_and_small_typos():
    media = [
        MediaItem("/media/01 - Langit Senja.mp3", 100.0),
        MediaItem("/media/02 - Pulang Ke Rumah.flac", 120.0),
        MediaItem("/media/03 - Cahaya Malam.wav", 130.0),
    ]

    selection = select_audio_titles(
        media,
        ["LANGIT SENJA.MP3", "Pulang ke Rmah", "03 cahaya malam"],
    )

    assert selection.selected_names == [
        "01 - Langit Senja.mp3",
        "02 - Pulang Ke Rumah.flac",
        "03 - Cahaya Malam.wav",
    ]


def test_missing_title_aborts_whole_selection_instead_of_guessing(feature):
    project = Project(audios=_library(20))
    controller = ProjectController(project)

    with pytest.raises(PlaylistSelectionError, match="Playlist tidak dibuat"):
        controller.execute(
            "select_audio_by_titles",
            {"titles": ["Lagu Pilihan 005", "Judul Yang Tidak Ada"]},
        )

    assert get_active_audio_paths(project) == []
    assert len(project.audios) == 20


def test_active_playlist_is_separate_from_media_and_drives_timeline(feature):
    project = Project(
        videos=[MediaItem("/media/footage.mp4", 1000.0)],
        audios=_library(200),
    )
    controller = ProjectController(project)
    titles = ["Lagu Pilihan 010", "Lagu Pilihan 003", "Lagu Pilihan 020"]

    controller.execute("select_audio_by_titles", {"titles": titles})
    controller.execute("set_slowmo", {"speed": 0.5})
    plan = PlaylistTimelineEngine().build(project)

    assert len(project.audios) == 200
    assert len(get_active_audio_paths(project)) == 3
    assert active_audio_indices(project) == [9, 2, 19]
    assert [clip.source_index for clip in plan.audio_clips] == [9, 2, 19]
    assert [clip.name for clip in plan.audio_clips] == [
        "010 - Lagu Pilihan 010",
        "003 - Lagu Pilihan 003",
        "020 - Lagu Pilihan 020",
    ]
    assert plan.planned_speed == pytest.approx(0.5)
    assert plan.duration == pytest.approx(190.0 + 183.0 + 200.0)


def test_project_roundtrip_persists_active_playlist(feature):
    project = Project(audios=_library(30))
    ProjectController(project).execute(
        "select_audio_by_titles",
        {"titles": ["Lagu Pilihan 007", "Lagu Pilihan 002"]},
    )

    raw = project.to_dict()
    restored = Project.from_dict(raw)

    assert len(restored.audios) == 30
    assert active_audio_indices(restored) == [6, 1]
    assert restored.total_audio_duration == pytest.approx(187.0 + 182.0)


def test_playlist_is_part_of_timeline_signature(feature):
    project = Project(
        videos=[MediaItem("/media/video.mp4", 1000.0)],
        audios=_library(10),
    )
    controller = ProjectController(project)
    controller.execute("select_audio_by_titles", {"titles": ["Lagu Pilihan 001"]})
    plan = PlaylistTimelineEngine().build(project)

    assert timeline_module.timeline_matches_project(plan, project) is True

    controller.execute("select_audio_by_titles", {"titles": ["Lagu Pilihan 002"]})
    assert timeline_module.timeline_matches_project(plan, project) is False


def test_agent_render_intent_implies_fresh_timeline_build(feature, tmp_path):
    project = Project(
        videos=[MediaItem("/media/video.mp4", 1000.0)],
        audios=_library(40),
    )
    executor = AppIntentExecutor(
        project,
        timeline_output_path=str(tmp_path / "Timeline_Auto.json"),
    )

    execution = executor.execute(
        [
            AgentAction(
                "select_audio_by_titles",
                {"titles": ["Lagu Pilihan 020", "Lagu Pilihan 005"]},
            ),
            AgentAction("set_slowmo", {"speed": 0.5}),
            AgentAction("render_timeline", {}),
        ]
    )

    assert getattr(execution, "render_requested", False) is True
    assert execution.timeline_plan is not None
    assert execution.timeline_plan.planned_speed == pytest.approx(0.5)
    assert [clip.source_index for clip in execution.timeline_plan.audio_clips] == [19, 4]
    assert (tmp_path / "Timeline_Auto.json").exists()


def test_gemini_exposes_playlist_and_render_tools_only_after_feature_install(feature):
    names = {tool["name"] for tool in gemini_agent_module.TOOLS}
    assert "select_audio_by_titles" in names
    assert "clear_audio_playlist" in names
    assert "render_timeline" in names
    assert FEATURE_ACTIONS.issubset(agent_actions_module.ALLOWED_ACTIONS)
    assert "20 lagu" in gemini_agent_module.SYSTEM


FEATURE_ACTIONS = {
    "select_audio_by_titles",
    "clear_audio_playlist",
    "render_timeline",
}
