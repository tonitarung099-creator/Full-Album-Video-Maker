from full_album_maker.editor_models import MediaAsset, ProjectDocument, SongInstance, seconds_to_tick
from full_album_maker.editor_session import EditorSession


def test_playhead_is_clamped_to_album_duration():
    doc = ProjectDocument.new_empty()
    audio = MediaAsset(kind="audio", locator="song.wav", source_duration_tick=seconds_to_tick(3))
    doc.media.append(audio)
    doc.playlist.entries.append(SongInstance(asset_id=audio.asset_id, source_out_tick=audio.source_duration_tick))
    session = EditorSession(doc)
    assert session.set_playhead(seconds_to_tick(9)) == seconds_to_tick(3)
    assert session.set_playhead(-10) == 0
