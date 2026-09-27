import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from full_album_maker.editor_models import ProjectDocument
from full_album_maker.editor_workspace import EditorWorkspace


def test_workspace_can_shrink_for_1366_layout_without_overlapping_children():
    app = QApplication.instance() or QApplication([])
    workspace = EditorWorkspace(ProjectDocument.new_empty())
    workspace.resize(720, 620)
    workspace.show()
    app.processEvents()

    # Layouts may compress controls, but the workspace itself must not force a
    # desktop wider than the user's target 1366px three-panel layout.
    assert workspace.minimumSizeHint().width() <= 760
    assert workspace.inspector.geometry().left() >= workspace.tabs.geometry().right() - 1
    workspace.close()
