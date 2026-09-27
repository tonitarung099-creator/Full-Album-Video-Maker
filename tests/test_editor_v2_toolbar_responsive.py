import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from full_album_maker.editor_models import ProjectDocument
from full_album_maker.responsive_workspace import ResponsiveEditorWorkspace


def test_workspace_actual_geometry_has_no_panel_overlap_at_compact_width():
    app = QApplication.instance() or QApplication([])
    workspace = ResponsiveEditorWorkspace(ProjectDocument.new_empty())
    workspace.resize(720, 620)
    workspace.show()
    app.processEvents()

    assert workspace.width() == 720
    assert workspace.compact_toolbar.geometry().right() <= workspace.width()
    assert workspace.inspector.geometry().left() >= workspace.tabs.geometry().right() - 1
    assert workspace.timeline_scroll.geometry().left() >= 0
    assert workspace.timeline_scroll.geometry().right() <= workspace.width()
    assert workspace.timeline_scroll.geometry().bottom() <= workspace.height()
    workspace.close()
