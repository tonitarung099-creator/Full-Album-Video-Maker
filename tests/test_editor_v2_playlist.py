from __future__ import annotations

from full_album_maker.auto_arrange import AUTO_KEY_PROPERTY, AutoArrange
from full_album_maker.editor_commands import AddLayer, SetPlaylistEntries
from full_album_maker.editor_controller import EditorController
from full_album_maker.editor_models import Layer, MediaAsset, ProjectDocument, TimeBinding
from full_album_maker.playlist_commands import MoveSong, RemoveSong, SetSongCover, SetSongTitle, SetSongVisual
from full_album_maker.playlist_service_v2 import PlaylistServiceV2
from full_album_maker.timeline_resolver import TimelineResolver


def _project_with_library(count: int = 3) -> ProjectDocument:
    doc = ProjectDocument.new_empty("Playlist S03")
    for index in range(count):
        doc.media.append(
            MediaAsset(
                kind="audio",
                locator=f"song-{index + 1:03d}.wav",
                original_name=f"Song {index + 1:03d}.wav",
                source_duration_tick=240_000 + index * 24_000,
                metadata={"title": f"Song {index + 1:03d}", "artist": "Artist"},
            )
        )
    doc.validate()
    return doc


def _add_visuals(doc: ProjectDocument, count: int) -> list[MediaAsset]:
    result = []
    for index in range(count):
        item = MediaAsset(
            kind="image",
            locator=f"visual-{index + 1}.png",
            original_name=f"visual-{index + 1}.png",
        )
        doc.media.append(item)
        result.append(item)
    doc.validate()
    return result


def test_select_20_from_200_keeps_media_library_intact():
    doc = _project_with_library(200)
    selected_assets = [asset.asset_id for asset in doc.media if asset.kind == "audio"][50:70]
    entries = PlaylistServiceV2.build_entries(doc, selected_assets)
    controller = EditorController(doc)
    controller.dispatch(SetPlaylistEntries(entries))
    snapshot = controller.snapshot()
    assert len(snapshot.media) == 200
    assert len(snapshot.playlist.entries) == 20
    assert [song.asset_id for song in snapshot.playlist.entries] == selected_assets


def test_same_audio_asset_can_appear_twice_with_unique_song_ids():
    doc = _project_with_library(1)
    asset_id = doc.media[0].asset_id
    entries = PlaylistServiceV2.build_entries(doc, [asset_id, asset_id])
    assert entries[0].asset_id == entries[1].asset_id
    assert entries[0].song_id != entries[1].song_id


def test_move_song_is_id_based_and_undo_restores_order():
    doc = _project_with_library(4)
    doc.playlist.entries = PlaylistServiceV2.use_all_audio(doc)
    controller = EditorController(doc)
    original = [song.song_id for song in controller.snapshot().playlist.entries]
    moved = original[0]
    controller.dispatch(MoveSong(moved, target_position=4))
    assert [song.song_id for song in controller.snapshot().playlist.entries] == original[1:] + [moved]
    controller.undo()
    assert [song.song_id for song in controller.snapshot().playlist.entries] == original


def test_remove_song_does_not_remove_media_and_undo_restores_instance():
    doc = _project_with_library(3)
    doc.playlist.entries = PlaylistServiceV2.use_all_audio(doc)
    controller = EditorController(doc)
    song = controller.snapshot().playlist.entries[1]
    controller.dispatch(RemoveSong(song.song_id))
    snapshot = controller.snapshot()
    assert len(snapshot.playlist.entries) == 2
    assert len(snapshot.media) == 3
    assert song.asset_id in snapshot.asset_map()
    controller.undo()
    assert controller.snapshot().playlist.entries[1].song_id == song.song_id


def test_title_cover_visual_stay_with_song_after_reorder():
    doc = _project_with_library(2)
    visuals = _add_visuals(doc, 2)
    doc.playlist.entries = PlaylistServiceV2.use_all_audio(doc)
    controller = EditorController(doc)
    first, second = controller.snapshot().playlist.entries
    controller.dispatch([
        SetSongTitle(first.song_id, "Judul Khusus"),
        SetSongCover(first.song_id, visuals[0].asset_id),
        SetSongVisual(first.song_id, visuals[1].asset_id),
    ])
    controller.dispatch(MoveSong(first.song_id, target_position=2))
    snapshot = controller.snapshot()
    moved = snapshot.playlist.entries[1]
    assert moved.song_id == first.song_id
    assert moved.display_title == "Judul Khusus"
    assert moved.cover_asset_id == visuals[0].asset_id
    assert moved.visual_asset_id == visuals[1].asset_id
    assert snapshot.playlist.entries[0].song_id == second.song_id


def test_filtered_projection_disables_ambiguous_drag_but_global_move_still_works():
    doc = _project_with_library(5)
    doc.playlist.entries = PlaylistServiceV2.use_all_audio(doc)
    rows = PlaylistServiceV2.rows(doc, "Song 003")
    assert [row.position for row in rows] == [3]
    assert not PlaylistServiceV2.reorder_allowed("Song 003")
    controller = EditorController(doc)
    song_id = rows[0].song_id
    controller.dispatch(MoveSong(song_id, target_position=1))
    assert controller.snapshot().playlist.entries[0].song_id == song_id


def test_markers_follow_playlist_order_and_exact_song_durations():
    doc = _project_with_library(3)
    doc.playlist.entries = PlaylistServiceV2.use_all_audio(doc)
    first_ids = [song.song_id for song in doc.playlist.entries]
    controller = EditorController(doc)
    controller.dispatch(MoveSong(first_ids[2], target_position=1))
    snapshot = controller.snapshot()
    markers = PlaylistServiceV2.markers(snapshot)
    assert [marker.song_id for marker in markers] == [first_ids[2], first_ids[0], first_ids[1]]
    assert markers[0].start_tick == 0
    assert all(marker.end_tick > marker.start_tick for marker in markers)
    assert all(markers[i].end_tick == markers[i + 1].start_tick for i in range(len(markers) - 1))


def test_auto_arrange_is_idempotent_and_preserves_manual_absolute_layer():
    doc = _project_with_library(2)
    visuals = _add_visuals(doc, 2)
    doc.playlist.entries = PlaylistServiceV2.use_all_audio(doc)
    for song, visual in zip(doc.playlist.entries, visuals):
        song.visual_asset_id = visual.asset_id
    manual = Layer(
        track_id=doc.tracks[0].track_id,
        type="text",
        name="Teks Manual",
        order=10,
        time_binding=TimeBinding(kind="absolute", start_tick=12_345, duration_tick=50_000),
        properties={"text": "Jangan dihapus"},
    )
    controller = EditorController(doc)
    controller.dispatch(AddLayer(manual))
    controller.mark_saved()

    controller.dispatch(AutoArrange())
    first = controller.snapshot()
    first_auto = [layer for layer in first.layers if layer.origin == "auto"]
    assert len(first_auto) == 2
    first_ids = {layer.properties[AUTO_KEY_PROPERTY]: layer.layer_id for layer in first_auto}
    manual_after = first.layer_map()[manual.layer_id]
    assert manual_after.time_binding.start_tick == 12_345
    assert manual_after.properties["text"] == "Jangan dihapus"

    controller.dispatch(AutoArrange())
    second = controller.snapshot()
    second_auto = [layer for layer in second.layers if layer.origin == "auto"]
    second_ids = {layer.properties[AUTO_KEY_PROPERTY]: layer.layer_id for layer in second_auto}
    assert second_ids == first_ids
    assert second.content_signature() == first.content_signature()
    assert second.layer_map()[manual.layer_id].time_binding.start_tick == 12_345


def test_auto_arrange_song_visual_anchor_moves_after_playlist_reorder():
    doc = _project_with_library(2)
    visuals = _add_visuals(doc, 2)
    doc.playlist.entries = PlaylistServiceV2.use_all_audio(doc)
    for song, visual in zip(doc.playlist.entries, visuals):
        song.visual_asset_id = visual.asset_id
    controller = EditorController(doc)
    controller.dispatch(AutoArrange())
    before = controller.snapshot()
    first_song = before.playlist.entries[0]
    first_layer = next(
        layer for layer in before.layers
        if layer.origin == "auto" and layer.time_binding.song_id == first_song.song_id
    )
    controller.dispatch(MoveSong(first_song.song_id, target_position=2))
    resolved = TimelineResolver().resolve(controller.snapshot())
    event = next(layer for layer in resolved.layers if layer.layer_id == first_layer.layer_id)
    assert event.intervals[0].start_tick == controller.snapshot().media[1].source_duration_tick


def test_auto_arrange_removes_only_its_owned_layer_after_song_removed():
    doc = _project_with_library(2)
    visuals = _add_visuals(doc, 2)
    doc.playlist.entries = PlaylistServiceV2.use_all_audio(doc)
    for song, visual in zip(doc.playlist.entries, visuals):
        song.visual_asset_id = visual.asset_id
    manual = Layer(
        track_id=doc.tracks[0].track_id,
        type="text",
        name="Manual",
        order=20,
        time_binding=TimeBinding(kind="absolute", start_tick=0, duration_tick=10_000),
        properties={"text": "manual"},
    )
    controller = EditorController(doc)
    controller.dispatch(AddLayer(manual))
    controller.dispatch(AutoArrange())
    removed_song = controller.snapshot().playlist.entries[0]
    controller.dispatch(RemoveSong(removed_song.song_id))
    controller.dispatch(AutoArrange())
    snapshot = controller.snapshot()
    assert manual.layer_id in snapshot.layer_map()
    assert all(layer.time_binding.song_id != removed_song.song_id for layer in snapshot.layers if layer.origin == "auto")
    assert len([layer for layer in snapshot.layers if layer.origin == "auto"]) == 1
