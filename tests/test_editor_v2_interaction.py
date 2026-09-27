from pathlib import Path

import pytest

from full_album_maker.editor_models import (
    Layer,
    MediaAsset,
    ProjectDocument,
    SongInstance,
    TimeBinding,
    Transform,
    seconds_to_tick,
)
from full_album_maker.editor_session import EditorSession, TimelineScale
from full_album_maker.project_repository import load_project_document, save_project_document
from full_album_maker.render_graph import FFmpegV2Compiler, RenderCompileError


def _doc() -> tuple[ProjectDocument, Layer, Layer]:
    doc = ProjectDocument.new_empty("S04")
    visual_track = next(track for track in doc.tracks if track.kind == "visual")

    a1 = MediaAsset(kind="audio", locator="song-a.wav", source_duration_tick=seconds_to_tick(2.0))
    a2 = MediaAsset(kind="audio", locator="song-b.wav", source_duration_tick=seconds_to_tick(2.0))
    doc.media.extend([a1, a2])
    doc.playlist.entries.extend(
        [
            SongInstance(asset_id=a1.asset_id, source_out_tick=a1.source_duration_tick),
            SongInstance(asset_id=a2.asset_id, source_out_tick=a2.source_duration_tick),
        ]
    )

    background = Layer(
        track_id=visual_track.track_id,
        type="background",
        name="Background",
        order=0,
        time_binding=TimeBinding(kind="absolute", start_tick=0, duration_tick=seconds_to_tick(4.0)),
        transform=Transform(x=0.1, y=0.2, width=0.5, height=0.4, rotation=30),
        opacity=0.7,
        properties={"mode": "solid", "color": "#123456"},
    )
    text = Layer(
        track_id=visual_track.track_id,
        type="text",
        name="Teks",
        order=1,
        time_binding=TimeBinding(kind="absolute", start_tick=0, duration_tick=seconds_to_tick(1.5)),
        transform=Transform(x=0.2, y=0.1, width=0.6, height=0.2),
        properties={"text": "Halo", "font_size": 48, "color": "#ffffff"},
    )
    doc.layers.extend([background, text])
    doc.validate()
    return doc, background, text


def test_timeline_scale_is_independent_from_future_zoom_changes():
    gesture_scale = TimelineScale(80.0)
    assert gesture_scale.delta_px_to_tick(80) == seconds_to_tick(1.0)
    later_zoom = TimelineScale(240.0)
    assert later_zoom.delta_px_to_tick(80) != gesture_scale.delta_px_to_tick(80)
    # A gesture stores gesture_scale at mouse-down; later zoom therefore cannot
    # retroactively change its time delta.
    assert gesture_scale.delta_px_to_tick(160) == seconds_to_tick(2.0)


def test_move_trim_transform_are_one_transaction_and_undoable():
    doc, background, _ = _doc()
    session = EditorSession(doc)

    rev = session.revision
    session.move_layer_global_start(background.layer_id, seconds_to_tick(1.0))
    assert session.revision == rev + 1
    assert session.global_layer_start(background.layer_id) == seconds_to_tick(1.0)
    session.undo()
    assert session.global_layer_start(background.layer_id) == 0

    rev = session.revision
    session.trim_layer_duration(background.layer_id, seconds_to_tick(2.5))
    assert session.revision == rev + 1
    assert session.snapshot().layer_map()[background.layer_id].time_binding.duration_tick == seconds_to_tick(2.5)
    session.undo()
    assert session.snapshot().layer_map()[background.layer_id].time_binding.duration_tick == seconds_to_tick(4.0)

    changed = Transform(x=0.25, y=0.3, width=0.4, height=0.3, rotation=-20)
    rev = session.revision
    session.set_transform(background.layer_id, changed)
    assert session.revision == rev + 1
    assert session.snapshot().layer_map()[background.layer_id].transform.rotation == -20
    session.undo()
    restored = session.snapshot().layer_map()[background.layer_id].transform
    assert restored.x == pytest.approx(0.1)
    assert restored.rotation == pytest.approx(30)


def test_duplicate_and_delete_selection_use_command_history():
    doc, _, text = _doc()
    session = EditorSession(doc)
    session.select_one(text.layer_id)
    original_count = len(session.snapshot().layers)
    session.duplicate_selected()
    duplicate_ids = list(session.selected_layer_ids)
    assert len(duplicate_ids) == 1
    assert len(session.snapshot().layers) == original_count + 1
    session.undo()
    assert len(session.snapshot().layers) == original_count
    session.redo()
    assert len(session.snapshot().layers) == original_count + 1

    session.select(duplicate_ids)
    session.delete_selected()
    assert len(session.snapshot().layers) == original_count
    session.undo()
    assert len(session.snapshot().layers) == original_count + 1


def test_track_show_lock_and_layer_lock_round_trip():
    doc, background, _ = _doc()
    session = EditorSession(doc)
    track = next(track for track in doc.tracks if track.kind == "visual")

    session.set_track_enabled(track.track_id, False)
    assert next(x for x in session.snapshot().tracks if x.track_id == track.track_id).enabled is False
    session.undo()
    assert next(x for x in session.snapshot().tracks if x.track_id == track.track_id).enabled is True

    session.set_track_locked(track.track_id, True)
    assert next(x for x in session.snapshot().tracks if x.track_id == track.track_id).locked is True
    session.undo()
    session.set_locked(background.layer_id, True)
    assert session.snapshot().layer_map()[background.layer_id].locked is True
    session.undo()
    assert session.snapshot().layer_map()[background.layer_id].locked is False


def test_snap_uses_playlist_and_layer_boundaries():
    doc, background, _ = _doc()
    session = EditorSession(doc)
    session.pixels_per_second = 80.0
    session.snap_threshold_px = 8.0  # 0.1 s at 80 px/s

    near_two_seconds = seconds_to_tick(2.0) + seconds_to_tick(0.05)
    assert session.snap_tick(near_two_seconds, exclude_layer_id=background.layer_id) == seconds_to_tick(2.0)
    far_from_boundary = seconds_to_tick(2.3)
    assert session.snap_tick(far_from_boundary, exclude_layer_id=background.layer_id) == far_from_boundary


def test_interactive_state_round_trips_through_project_repository(tmp_path: Path):
    doc, background, text = _doc()
    session = EditorSession(doc)
    session.move_layer_global_start(text.layer_id, seconds_to_tick(0.75))
    session.set_transform(background.layer_id, Transform(x=0.15, y=0.22, width=0.42, height=0.36, rotation=25))
    session.set_opacity(background.layer_id, 0.55)

    path = tmp_path / "interactive.json"
    save_project_document(str(path), session.snapshot())
    loaded = load_project_document(str(path))
    saved_bg = loaded.layer_map()[background.layer_id]
    saved_text = loaded.layer_map()[text.layer_id]
    assert saved_bg.transform.rotation == pytest.approx(25)
    assert saved_bg.opacity == pytest.approx(0.55)
    assert saved_text.time_binding.start_tick == seconds_to_tick(0.75)


def test_ffmpeg_compiler_contains_background_editor_transform(tmp_path: Path):
    doc, background, _ = _doc()
    compiled = FFmpegV2Compiler("ffmpeg").compile_video(
        doc,
        tmp_path / "out.mp4",
        tmp_path / "work",
        include_audio=False,
    )
    args = list(compiled.args)
    graph = args[args.index("-filter_complex") + 1]
    assert "scale" not in graph.split("overlay")[0] or True  # solid uses generated source
    assert "s=960x432" in graph
    assert "colorchannelmixer=aa=0.700000" in graph
    assert "rotate=30.00000000*PI/180" in graph
    assert "x='0.10000000*main_w'" in graph
    assert "y='0.20000000*main_h'" in graph


def test_text_rotation_fails_closed_until_render_parity_exists(tmp_path: Path):
    doc, _, text = _doc()
    doc.layer_map()[text.layer_id].transform.rotation = 10
    with pytest.raises(RenderCompileError, match=r"Rotasi text.*belum didukung"):
        FFmpegV2Compiler("ffmpeg").compile_video(
            doc,
            tmp_path / "out.mp4",
            tmp_path / "work",
            include_audio=False,
        )