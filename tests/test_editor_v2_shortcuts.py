import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from full_album_maker.editor_models import ProjectDocument
from full_album_maker.editor_workspace import EditorWorkspace


def test_delete_shortcut_does_not_fire_while_text_input_has_focus():
    app = QApplication.instance() or QApplication([])
    workspace = EditorWorkspace(ProjectDocument.new_empty())
    workspace.show()
    workspace.playlist.search.setFocus()
    app.processEvents()

    before = workspace.document().to_dict()
    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
    workspace.keyPressEvent(event)
    assert workspace.document().to_dict() == before
    workspace.close()
