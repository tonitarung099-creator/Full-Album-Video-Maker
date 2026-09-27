from __future__ import annotations

import json
from pathlib import Path

import pytest

from full_album_maker.editor_commands import AddLayer, CommandError, ReorderSongs, SetCanvasBackground
from full_album_maker.editor_controller import EditorController, RevisionConflict
from full_album_maker.editor_models import (
    Layer,
    MediaAsset,
    ProjectDocument,
    ProjectSchemaError,
    SongInstance,
    TimeBinding,
)
from full_album_maker.project_repository import load_project_document, save_project_document
from full_album_maker.project_migrations import migrate_project_v1
from full_album_maker.timeline_resolver import TimelineResolver


def _doc_with_two_songs() -> ProjectDocument:
    doc = ProjectDocument.new_empty()
    a1 = MediaAsset(kind="audio", locator="A.mp3", source_duration_tick=240_000)
    a2 = MediaAsset(kind="audio", locator="B.mp3", source_duration_tick=480_000)
    doc.media.extend([a1, a2])
    doc.playlist.entries.extend([
        SongInstance(asset_id=a1.asset_id, source_out_tick=a1.source_duration_tick),
        SongInstance(asset_id=a2.asset_id, source_out_tick=a2.source_duration_tick),
    ])
    doc.validate()
    return doc


def test_empty_project_round_trip_and_explicit_empty_playlist(tmp_path: Path):
    doc = ProjectDocument.new_empty("Kosong")
    assert doc.layers == []
    assert doc.playlist.entries == []
    path = tmp_path / "empty.json"
    save_project_document(str(path), doc)
    loaded = load_project_document(str(path))
    assert loaded.to_dict() == doc.to_dict()


def test_future_schema_fails_without_rewrite(tmp_path: Path):
    doc = ProjectDocument.new_empty()
    data = doc.to_dict()
    data["schema_version"] = 999
    path = tmp_path / "future.json"
    original = json.dumps(data)
    path.write_text(original, encoding="utf-8")
    with pytest.raises(ProjectSchemaError, match="lebih baru"):
        load_project_document(str(path))
    assert path.read_text(encoding="utf-8") == original


def test_migration_keeps_duplicate_song_occurrences_and_legacy_title():
    legacy = {
        "version": 1,
        "videos": [{"path": "bg.mp4", "duration": 10}],
        "audios": [
            {"path": "Duka.mp3", "duration": 4, "display_title": "Duka", "display_artist": "Last Child"},
            {"path": "Lagu B.mp3", "duration": 5},
        ],
        "active_audio_paths": ["Duka.mp3", "Duka.mp3", "Lagu B.mp3"],
        "settings": {"width": 1920, "height": 1080, "fps": 30, "loop_mode": "auto"},
        "visual_settings": {"title_mode": "intro6", "title_animation": "fade", "visual_mode": "sequential"},
        "visual_order": ["bg.mp4"],
    }
    doc = migrate_project_v1(legacy)
    assert len(doc.playlist.entries) == 3
    assert doc.playlist.entries[0].asset_id == doc.playlist.entries[1].asset_id
    assert doc.playlist.entries[0].song_id != doc.playlist.entries[1].song_id
    assert any(layer.type == "song_title" for layer in doc.layers)
    assert doc.extensions["legacy_v1"]["visual_settings"]["title_mode"] == "intro6"


def test_legacy_empty_active_paths_means_all_audio():
    legacy = {
        "version": 1,
        "videos": [],
        "audios": [{"path": "a.mp3", "duration": 1}, {"path": "b.mp3", "duration": 2}],
        "active_audio_paths": [],
        "settings": {"width": 1920, "height": 1080, "fps": 30},
    }
    doc = migrate_project_v1(legacy)
    assert len(doc.playlist.entries) == 2


def test_command_batch_is_atomic_and_revision_checked():
    doc = _doc_with_two_songs()
    controller = EditorController(doc)
    visual_track = controller.snapshot().tracks[0]
    good = Layer(track_id=visual_track.track_id, type="text", name="Judul", time_binding=TimeBinding(kind="album"))
    bad = Layer(track_id="00000000-0000-0000-0000-000000000000", type="text", name="Rusak")
    before = controller.snapshot().to_dict()
    with pytest.raises(ProjectSchemaError):
        controller.dispatch([AddLayer(good), AddLayer(bad)], expected_revision=0)
    assert controller.snapshot().to_dict() == before
    with pytest.raises(RevisionConflict):
        controller.dispatch(SetCanvasBackground("#222222"), expected_revision=9)


def test_undo_back_to_saved_state_is_clean_and_redo_works():
    controller = EditorController(_doc_with_two_songs())
    assert not controller.is_dirty
    controller.dispatch(SetCanvasBackground("#202020"), expected_revision=0)
    assert controller.is_dirty
    changed_revision = controller.revision
    controller.undo()
    assert controller.revision == changed_revision + 1
    assert not controller.is_dirty
    controller.redo()
    assert controller.is_dirty
    assert controller.snapshot().canvas.background_color == "#202020"


def test_reorder_uses_song_ids_and_song_range_stays_on_same_songs():
    doc = _doc_with_two_songs()
    first, second = doc.playlist.entries
    visual_track = doc.tracks[0]
    layer = Layer(
        track_id=visual_track.track_id,
        type="spectrum",
        name="Range",
        time_binding=TimeBinding(kind="song_range", ordered_song_ids=[first.song_id]),
    )
    doc.layers.append(layer)
    controller = EditorController(doc)
    controller.dispatch(ReorderSongs([second.song_id, first.song_id]))
    resolved = TimelineResolver().resolve(controller.snapshot())
    resolved_layer = next(x for x in resolved.layers if x.layer_id == layer.layer_id)
    assert [(x.start_tick, x.end_tick) for x in resolved_layer.intervals] == [(480_000, 720_000)]


def test_reorder_rejects_missing_or_duplicate_ids_without_partial_mutation():
    doc = _doc_with_two_songs()
    controller = EditorController(doc)
    first = doc.playlist.entries[0].song_id
    before = [x.song_id for x in controller.snapshot().playlist.entries]
    with pytest.raises(CommandError):
        controller.dispatch(ReorderSongs([first, first]))
    assert [x.song_id for x in controller.snapshot().playlist.entries] == before


def test_atomic_save_failure_does_not_replace_existing_file(tmp_path: Path, monkeypatch):
    import full_album_maker.project_repository as repository

    path = tmp_path / "project.json"
    path.write_text("OLD", encoding="utf-8")

    def fail(*args, **kwargs):
        raise OSError("disk penuh")

    monkeypatch.setattr(repository, "atomic_write_text", fail)
    with pytest.raises(OSError, match="disk penuh"):
        repository.save_project_document(str(path), ProjectDocument.new_empty())
    assert path.read_text(encoding="utf-8") == "OLD"


def test_timeline_v1_is_identified_but_not_silently_loaded_as_project(tmp_path: Path):
    payload = {"version": 1, "duration": 3.0, "audio_clips": [], "video_clips": []}
    path = tmp_path / "Timeline_Final.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ProjectSchemaError, match="TimelinePlan v1"):
        load_project_document(str(path))
