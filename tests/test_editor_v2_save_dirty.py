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


def test_set_document_can_explicitly_start_dirty_without_fake_edit():
    session = EditorSession(ProjectDocument.new_empty("Awal"))
    replacement = ProjectDocument.new_empty("Hasil Import")

    session.set_document(replacement, mark_saved=False)

    assert session.snapshot().name == "Hasil Import"
    assert session.is_dirty
    assert not session.can_undo
    assert not session.can_redo

    session.mark_saved()
    assert not session.is_dirty
