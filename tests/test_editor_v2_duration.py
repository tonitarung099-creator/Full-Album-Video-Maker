from full_album_maker.editor_models import MediaAsset, ProjectDocument, SongInstance, seconds_to_tick
from full_album_maker.editor_session import EditorSession


def test_album_end_matches_enabled_packed_playlist():
    doc = ProjectDocument.new_empty()
    a = MediaAsset(kind="audio", locator="a.wav", source_duration_tick=seconds_to_tick(2))
    b = MediaAsset(kind="audio", locator="b.wav", source_duration_tick=seconds_to_tick(3))
    doc.media.extend([a, b])
    doc.playlist.entries.extend([
        SongInstance(asset_id=a.asset_id, source_out_tick=a.source_duration_tick),
        SongInstance(asset_id=b.asset_id, source_out_tick=b.source_duration_tick),
    ])
    assert EditorSession(doc).album_end_tick() == seconds_to_tick(5)
