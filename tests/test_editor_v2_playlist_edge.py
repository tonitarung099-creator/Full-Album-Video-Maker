from __future__ import annotations

import pytest

from full_album_maker.auto_arrange import AutoArrange
from full_album_maker.editor_commands import CommandError
from full_album_maker.editor_controller import EditorController
from full_album_maker.editor_models import Layer, MediaAsset, ProjectDocument, TimeBinding, new_id
from full_album_maker.playlist_service_v2 import PlaylistServiceV2


def _doc() -> ProjectDocument:
    doc = ProjectDocument.new_empty("Edge")
    audio = MediaAsset(kind="audio", locator="song.wav", source_duration_tick=240_000)
    image = MediaAsset(kind="image", locator="visual.png")
    doc.media.extend([audio, image])
    doc.playlist.entries = PlaylistServiceV2.build_entries(doc, [audio.asset_id])
    doc.playlist.entries[0].visual_asset_id = image.asset_id
    doc.validate()
    return doc


def test_playlist_markers_survive_unrelated_unresolved_visual_layer():
    doc = _doc()
    doc.layers.append(
        Layer(
            track_id=doc.tracks[0].track_id,
            type="text",
            name="Anchor Rusak Manual",
            time_binding=TimeBinding(kind="song", song_id=new_id()),
            properties={"text": "manual"},
        )
    )
    doc.validate()
    markers = PlaylistServiceV2.markers(doc)
    assert len(markers) == 1
    assert markers[0].start_tick == 0
    assert markers[0].end_tick == 240_000


def test_auto_arrange_respects_locked_owned_layer():
    controller = EditorController(_doc())
    controller.dispatch(AutoArrange())
    locked = controller.snapshot()
    auto_layer = next(layer for layer in locked.layers if layer.origin == "auto")
    auto_layer.locked = True
    controller = EditorController(locked)
    with pytest.raises(CommandError, match="terkunci"):
        controller.dispatch(AutoArrange())
