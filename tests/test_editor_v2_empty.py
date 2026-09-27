from full_album_maker.editor_models import ProjectDocument
from full_album_maker.editor_session import EditorSession


def test_empty_editor_can_zoom_seek_and_save_state_without_song():
    session = EditorSession(ProjectDocument.new_empty())
    session.pixels_per_second = 120
    assert session.set_playhead(999) == 0
    assert session.snapshot().playlist.entries == []
    assert session.resolved().duration_tick == 0
