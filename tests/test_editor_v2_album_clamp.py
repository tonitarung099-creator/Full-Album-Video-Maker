from full_album_maker.editor_models import Layer, MediaAsset, ProjectDocument, SongInstance, TimeBinding, seconds_to_tick
from full_album_maker.timeline_resolver import TimelineResolver


def test_visual_interval_is_clamped_to_album_end():
    doc = ProjectDocument.new_empty()
    audio = MediaAsset(kind="audio", locator="a.wav", source_duration_tick=seconds_to_tick(2))
    doc.media.append(audio)
    doc.playlist.entries.append(SongInstance(asset_id=audio.asset_id, source_out_tick=audio.source_duration_tick))
    track = next(x for x in doc.tracks if x.kind == "visual")
    layer = Layer(track_id=track.track_id, type="text", time_binding=TimeBinding(kind="absolute", start_tick=seconds_to_tick(1), duration_tick=seconds_to_tick(5)))
    doc.layers.append(layer)
    resolved = TimelineResolver().resolve(doc)
    item = next(x for x in resolved.layers if x.layer_id == layer.layer_id)
    assert item.intervals[0].end_tick == seconds_to_tick(2)
