from __future__ import annotations

import json

import pytest

from full_album_maker.agent_actions import AgentAction
from full_album_maker.ai_editor import (
    AIEditorAmbiguity,
    AIEditorEnvelope,
    AIEditorError,
    deterministic_action_id,
)
from full_album_maker.ai_editor_v14 import (
    V14AIEditorExecutor,
    V14_EDITOR_TOOLS,
    V14EditorAIContextBuilder,
)
from full_album_maker.editor_controller import EditorController
from full_album_maker.editor_models import (
    MediaAsset,
    ProjectDocument,
    SongInstance,
    seconds_to_tick,
)


def _document() -> tuple[ProjectDocument, list[SongInstance], dict[str, MediaAsset]]:
    doc = ProjectDocument.new_empty("AI v1.4")
    duration = seconds_to_tick(10.0)
    audio1 = MediaAsset(
        kind="audio",
        locator="C:/RAHASIA/01 - Satu.wav",
        original_name="01 - Satu.wav",
        source_duration_tick=duration,
    )
    audio2 = MediaAsset(
        kind="audio",
        locator="C:/RAHASIA/02 - Dua.wav",
        original_name="02 - Dua.wav",
        source_duration_tick=duration,
    )
    cover = MediaAsset(
        kind="image",
        locator="C:/RAHASIA/Satu.png",
        original_name="Satu.png",
    )
    photo = MediaAsset(
        kind="image",
        locator="C:/RAHASIA/Dua.jpg",
        original_name="Dua.jpg",
    )
    video = MediaAsset(
        kind="video",
        locator="C:/RAHASIA/Dua.mp4",
        original_name="Dua.mp4",
        source_duration_tick=duration,
    )
    doc.media.extend([audio1, audio2, cover, photo, video])
    song1 = SongInstance(
        asset_id=audio1.asset_id,
        source_out_tick=duration,
        display_title="Satu",
        display_artist="Artist A",
    )
    song2 = SongInstance(
        asset_id=audio2.asset_id,
        source_out_tick=duration,
        display_title="Dua",
        display_artist="Artist B",
    )
    doc.playlist.entries.extend([song1, song2])
    doc.validate()
    return doc, [song1, song2], {
        "cover": cover,
        "photo": photo,
        "video": video,
        "audio1": audio1,
        "audio2": audio2,
    }


def _envelope(doc: ProjectDocument, key: str, actions: list[AgentAction]) -> AIEditorEnvelope:
    return AIEditorEnvelope(
        action_id=deterministic_action_id(doc.project_id, doc.revision, key, actions),
        project_id=doc.project_id,
        expected_revision=doc.revision,
        actions=tuple(actions),
    )


def test_v14_tool_registry_exposes_new_features_without_removing_s09_tools():
    names = [item["name"] for item in V14_EDITOR_TOOLS]
    assert "render_project" in names
    assert "add_spectrum" in names
    assert "add_circular_spectrum" in names
    assert "set_song_cover" in names
    assert "set_song_visual" in names
    assert "set_song_visual_style" in names
    assert "set_timeline_mode" in names
    assert "set_song_timing" in names
    assert len(names) == len(set(names))


def test_v14_context_adds_safe_media_ids_and_timing_without_paths():
    doc, songs, assets = _document()
    songs[0].cover_asset_id = assets["cover"].asset_id
    songs[1].visual_asset_id = assets["video"].asset_id
    context = V14EditorAIContextBuilder(max_media=20).build(
        doc,
        user_text="dua video",
    )
    raw = json.dumps(context, ensure_ascii=False)
    assert context["playlist_mode"] == "packed"
    assert assets["cover"].asset_id in raw
    assert assets["video"].asset_id in raw
    assert "Satu.png" in raw
    assert "Dua.mp4" in raw
    assert "RAHASIA" not in raw
    assert "locator" not in raw
    assert any(item["cover_asset_id"] == assets["cover"].asset_id for item in context["songs"])
    assert any(item["visual_asset_id"] == assets["video"].asset_id for item in context["songs"])


def test_bulk_cover_and_visual_assignment_is_one_revision_and_one_undo():
    doc, songs, assets = _document()
    controller = EditorController(doc)
    executor = V14AIEditorExecutor(controller)
    actions = [
        AgentAction(
            "set_song_cover",
            {"song_ids": [songs[0].song_id, songs[1].song_id], "asset_id": assets["cover"].asset_id},
        ),
        AgentAction(
            "set_song_visual",
            {"song_ids": [songs[0].song_id, songs[1].song_id], "asset_id": assets["video"].asset_id},
        ),
    ]
    result = executor.execute(_envelope(doc, "bulk", actions))
    assert result.project_changed is True
    assert controller.revision == doc.revision + 1
    current = controller.snapshot()
    for song in current.playlist.entries:
        assert song.cover_asset_id == assets["cover"].asset_id
        assert song.visual_asset_id == assets["video"].asset_id

    controller.undo()
    restored = controller.snapshot()
    assert all(song.cover_asset_id is None for song in restored.playlist.entries)
    assert all(song.visual_asset_id is None for song in restored.playlist.entries)


def test_asset_query_ambiguity_fails_closed_without_mutation():
    doc, songs, assets = _document()
    duplicate = MediaAsset(
        kind="image",
        locator="D:/LAIN/Satu.webp",
        original_name="Satu.webp",
    )
    doc.media.append(duplicate)
    doc.validate()
    controller = EditorController(doc)
    before = controller.snapshot().content_signature()
    action = AgentAction(
        "set_song_cover",
        {"song_id": songs[0].song_id, "asset_query": "Satu"},
    )
    with pytest.raises(AIEditorAmbiguity):
        V14AIEditorExecutor(controller).execute(_envelope(doc, "ambiguous", [action]))
    assert controller.snapshot().content_signature() == before


def test_auto_match_cover_respects_only_empty_and_stays_local():
    doc, songs, assets = _document()
    songs[0].cover_asset_id = assets["photo"].asset_id
    controller = EditorController(doc)
    action = AgentAction("auto_match_covers", {"only_empty": True})
    V14AIEditorExecutor(controller).execute(_envelope(doc, "match", [action]))
    current = controller.snapshot().song_map()
    assert current[songs[0].song_id].cover_asset_id == assets["photo"].asset_id
    # "Dua" has both image and video, but Cover matcher only accepts image.
    assert current[songs[1].song_id].cover_asset_id == assets["photo"].asset_id


def test_circular_spectrum_and_song_visual_style_are_created_atomically():
    doc, _songs, _assets = _document()
    controller = EditorController(doc)
    actions = [
        AgentAction(
            "add_circular_spectrum",
            {"inner_ratio": 0.64, "color": "#55eeff", "gain": 1.5},
        ),
        AgentAction(
            "set_song_visual_style",
            {
                "fit": "fill",
                "image_motion": "pan_left",
                "video_playback": "freeze",
                "transition": "slide_right",
                "transition_seconds": 1.2,
            },
        ),
    ]
    V14AIEditorExecutor(controller).execute(_envelope(doc, "visual-style", actions))
    current = controller.snapshot()
    circular = next(layer for layer in current.layers if layer.type == "spectrum")
    assert circular.properties["style"] == "circular_spectrum"
    assert circular.properties["inner_ratio"] == pytest.approx(0.64)
    song_visual = next(layer for layer in current.layers if layer.type == "song_visual")
    assert song_visual.properties["image_motion"] == "pan_left"
    assert song_visual.properties["video_playback"] == "freeze"
    assert song_visual.properties["transition"] == "slide_right"
    assert song_visual.properties["transition_seconds"] == pytest.approx(1.2)

    controller.undo()
    assert not controller.snapshot().layers


def test_song_timing_enables_free_mode_and_valid_crossfade_in_one_transaction():
    doc, songs, _assets = _document()
    controller = EditorController(doc)
    action = AgentAction(
        "set_song_timing",
        {
            "song_id": songs[1].song_id,
            "start_seconds": 9.0,
            "crossfade_seconds": 1.0,
        },
    )
    V14AIEditorExecutor(controller).execute(_envelope(doc, "timing", [action]))
    current = controller.snapshot()
    assert current.playlist.mode == "free"
    second = current.song_map()[songs[1].song_id]
    assert second.free_start_tick == seconds_to_tick(9.0)
    assert second.crossfade_in_tick == seconds_to_tick(1.0)

    controller.undo()
    restored = controller.snapshot()
    assert restored.playlist.mode == "packed"
    assert all(song.free_start_tick is None for song in restored.playlist.entries)
    assert all(song.crossfade_in_tick == 0 for song in restored.playlist.entries)


def test_invalid_overlap_rolls_back_free_conversion_and_timing():
    doc, songs, _assets = _document()
    controller = EditorController(doc)
    before = controller.snapshot().content_signature()
    action = AgentAction(
        "set_song_timing",
        {
            "song_id": songs[1].song_id,
            "start_seconds": 9.0,
            "crossfade_seconds": 0.0,
        },
    )
    with pytest.raises(AIEditorError):
        V14AIEditorExecutor(controller).execute(_envelope(doc, "bad-timing", [action]))
    assert controller.snapshot().content_signature() == before
    assert controller.snapshot().playlist.mode == "packed"
