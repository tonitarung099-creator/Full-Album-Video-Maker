import pytest

from full_album_maker.editor_commands import CommandError
from full_album_maker.editor_models import Layer, MediaAsset, ProjectDocument, SongInstance, TimeBinding, seconds_to_tick
from full_album_maker.editor_session import EditorSession


def test_locked_layer_rejects_timeline_move_without_partial_mutation():
    doc = ProjectDocument.new_empty()
    audio = MediaAsset(kind="audio", locator="a.wav", source_duration_tick=seconds_to_tick(5))
    doc.media.append(audio)
    doc.playlist.entries.append(SongInstance(asset_id=audio.asset_id, source_out_tick=audio.source_duration_tick))
    track = next(x for x in doc.tracks if x.kind == "visual")
    layer = Layer(track_id=track.track_id, type="text", locked=True, time_binding=TimeBinding(kind="absolute", duration_tick=seconds_to_tick(2)))
    doc.layers.append(layer)
    session = EditorSession(doc)
    before = session.snapshot().to_dict()
    with pytest.raises(CommandError, match="terkunci"):
        session.move_layer_global_start(layer.layer_id, seconds_to_tick(1))
    assert session.snapshot().to_dict() == before
