from full_album_maker.editor_models import Layer, MediaAsset, ProjectDocument, SongInstance, TimeBinding, seconds_to_tick
from full_album_maker.editor_session import EditorSession


def test_single_move_gesture_maps_to_single_revision_increment():
    doc = ProjectDocument.new_empty()
    audio = MediaAsset(kind="audio", locator="a.wav", source_duration_tick=seconds_to_tick(5))
    doc.media.append(audio)
    doc.playlist.entries.append(SongInstance(asset_id=audio.asset_id, source_out_tick=audio.source_duration_tick))
    track = next(x for x in doc.tracks if x.kind == "visual")
    layer = Layer(track_id=track.track_id, type="text", time_binding=TimeBinding(kind="absolute", duration_tick=seconds_to_tick(2)))
    doc.layers.append(layer)
    session = EditorSession(doc)
    before = session.revision
    session.move_layer_global_start(layer.layer_id, seconds_to_tick(1))
    assert session.revision == before + 1
