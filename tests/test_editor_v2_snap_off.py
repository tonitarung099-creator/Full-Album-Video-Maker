from full_album_maker.editor_models import MediaAsset, ProjectDocument, SongInstance, seconds_to_tick
from full_album_maker.editor_session import EditorSession


def test_snap_can_be_disabled_for_precise_free_move():
    doc = ProjectDocument.new_empty()
    audio = MediaAsset(kind="audio", locator="a.wav", source_duration_tick=seconds_to_tick(2))
    doc.media.append(audio)
    doc.playlist.entries.append(SongInstance(asset_id=audio.asset_id, source_out_tick=audio.source_duration_tick))
    session = EditorSession(doc)
    session.snap_enabled = False
    value = seconds_to_tick(1.97)
    assert session.snap_tick(value) == value
