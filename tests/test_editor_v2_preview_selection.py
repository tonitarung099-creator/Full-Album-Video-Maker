from full_album_maker.editor_models import ProjectDocument
from full_album_maker.editor_session import EditorSession


def test_editor_selection_playhead_and_zoom_are_not_persisted_project_state():
    doc = ProjectDocument.new_empty()
    session = EditorSession(doc)
    before = session.snapshot().to_dict()
    session.playhead_tick = 12345
    session.pixels_per_second = 222.0
    session.snap_enabled = False
    session.selected_layer_ids = ["not-a-real-layer"]
    after = session.snapshot().to_dict()
    assert after == before
