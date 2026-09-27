from full_album_maker.editor_models import ProjectDocument
from full_album_maker.editor_session import EditorSession


def test_mark_saved_resets_editor_dirty_checkpoint():
    session = EditorSession(ProjectDocument.new_empty())
    session.add_text_layer("Halo")
    assert session.is_dirty
    session.mark_saved()
    assert not session.is_dirty
    session.undo()
    assert session.is_dirty
